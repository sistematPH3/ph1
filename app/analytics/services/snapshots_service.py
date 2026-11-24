"""Servicios del cajón de estadísticas (Rápido 1 - Módulo 8).

Orquesta la generación de snapshots (UPSERT idempotente), la evaluación de
alarmas de irregularidad, la configuración (factor y mínimo) y los datos que
consumen el dashboard del Admin y el panel /estadisticas.
"""
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_

from app.extensions import db
from app.time_utils import current_ve_time, ve_a_utc
from app.models.statistics_model import SnapshotMetric, SnapshotPeriodType, StatisticsSnapshot
from app.models.waste_model import AppParameter, AuditLog, Waste
from app.models.logistics_model import Location, Movement, Purchase
from app.analytics.repositories import snapshots_repository as repo
from app.analytics.requests.statistics_validators import validate_config_payload
from app.inventory.services import product_cost_service
from app.logistics.repositories.movement_dispute_repository import MovementDisputeRepository

logger = logging.getLogger(__name__)

PERIOD_TYPES = (
    SnapshotPeriodType.WEEKLY,
    SnapshotPeriodType.MONTHLY,
    SnapshotPeriodType.QUARTERLY,
    SnapshotPeriodType.ANNUAL,
)

METRICAS = (
    SnapshotMetric.PURCHASES,
    SnapshotMetric.KITCHEN_CONSUMPTION,
    SnapshotMetric.WASTE,
    SnapshotMetric.TRANSFERS,
)

FACTOR_DEFECTO = Decimal('2.0')
MINIMO_DEFECTO = Decimal('100.00')

CENTESIMA = Decimal('0.01')

# El gráfico de evolución dibuja esta cantidad de períodos. La generación
# perezosa usa el mismo valor para que las cuatro series (compras, consumo de
# cocina, mermas y traslados) tengan snapshots en todos los puntos graficados.
PERIODOS_GRAFICO = 13


def _redondear(valor):
    return Decimal(str(valor)).quantize(CENTESIMA, rounding=ROUND_HALF_UP)


def _tasas_en(fecha, cache=None):
    """Tasas BCV vigentes para la fecha (Bs por unidad), con caché por fecha."""
    from app.inventory.repositories import product_cost_repository
    return product_cost_repository.tasas_bcv(fecha, cache=cache)


def calcular_periodo(period_type, referencia=None):
    """Devuelve (inicio, fin) como fechas del período que contiene a `referencia`.

    La referencia por defecto usa el reloj de Venezuela (UTC-4, mismo con el
    que se escriben Movement.date, Waste.date y los AuditLog de consumo) para
    que los límites del período no se desfasen 4 horas del reloj del negocio.
    """
    if referencia is None:
        referencia = current_ve_time().date()
    elif isinstance(referencia, datetime):
        referencia = referencia.date()
    if period_type == SnapshotPeriodType.WEEKLY:
        inicio = referencia - timedelta(days=referencia.weekday())
        fin = inicio + timedelta(days=6)
    elif period_type == SnapshotPeriodType.MONTHLY:
        inicio = referencia.replace(day=1)
        if referencia.month == 12:
            fin = inicio.replace(year=inicio.year + 1, month=1) - timedelta(days=1)
        else:
            fin = inicio.replace(month=inicio.month + 1) - timedelta(days=1)
    elif period_type == SnapshotPeriodType.QUARTERLY:
        tromestre = (referencia.month - 1) // 3
        inicio = referencia.replace(month=tromestre * 3 + 1, day=1)
        fin = (inicio.replace(month=inicio.month + 3)
               if inicio.month <= 9 else inicio.replace(year=inicio.year + 1, month=1)) - timedelta(days=1)
    else:  # ANNUAL
        inicio = referencia.replace(month=1, day=1)
        fin = inicio.replace(year=inicio.year + 1) - timedelta(days=1)
    return inicio, fin


def periodos_historia(period_type, limite=13, corte=None):
    """Los últimos `limite` períodos (inicio, fin), terminando en el actual."""
    actual_inicio, actual_fin = calcular_periodo(period_type, corte)
    periodos = [(actual_inicio, actual_fin)]
    for i in range(1, limite):
        inicio_actual, _ = periodos[-1]
        # Restamos un día y recalculamos para obtener el período anterior.
        prev_ref = inicio_actual - timedelta(days=1)
        inicio, fin = calcular_periodo(period_type, prev_ref)
        periodos.append((inicio, fin))
    periodos.reverse()
    return periodos


def _etiqueta_periodo(period_type, inicio):
    if period_type == SnapshotPeriodType.WEEKLY:
        return inicio.strftime('%d/%m')
    if period_type == SnapshotPeriodType.MONTHLY:
        return inicio.strftime('%m/%Y')
    if period_type == SnapshotPeriodType.QUARTERLY:
        return f"T{(inicio.month - 1) // 3 + 1} {inicio.year}"
    return str(inicio.year)


def _costo_usd_bs_eur(product_id, fecha, cache=None):
    """Costo unitario del producto en USD/BS/EUR para la fecha (un solo motor)."""
    unit_usd = product_cost_service.obtener_costo_unitario(product_id, fecha=fecha, moneda='USD')
    tasas = _tasas_en(fecha, cache=cache)
    tasa_usd = tasas.get('USD')
    tasa_eur = tasas.get('EUR')
    unit_bs = _redondear(unit_usd * tasa_usd) if tasa_usd else Decimal('0.00')
    # USD→EUR = USD * (Bs/USD) / (Bs/EUR); la tasa EUR no se multiplica.
    unit_eur = (_redondear(unit_usd * tasa_usd / tasa_eur)
                if tasa_eur and tasa_usd else Decimal('0.00'))
    return unit_usd, unit_bs, unit_eur


def _agregar(filas, valor_usd_bs_eur):
    """Acumula filas [{location_id, quantity}|extra] por sede hasta 3 monedas."""
    resultado = {}
    for fila in filas:
        loc = fila['location_id']
        agg = resultado.setdefault(loc, {
            'monto_usd': Decimal('0.00'), 'monto_bs': Decimal('0.00'),
            'monto_eur': Decimal('0.00'), 'cantidad': Decimal('0.00'),
            'registros': 0,
        })
        usd, bs, eur = valor_usd_bs_eur(fila)
        agg['monto_usd'] += usd
        agg['monto_bs'] += bs
        agg['monto_eur'] += eur
        agg['cantidad'] += fila['quantity']
        agg['registros'] += 1
    return resultado


def _agregar_compras(filas, cache):
    """Valoriza CADA FACTURA desde su cabecera (no desde el precio unitario).

    `total_foreign` ya es el importe exacto de la factura y `total_bs` su
    equivalente con la tasa guardada al registrarla. Así la alarma compara el
    mismo dinero que muestra Gestión de Compras, sin el desvío de redondeo del
    detalle (160 × 0,63 = 100,80 frente a una cabecera de 100,00).
    """
    def valor(fila):
        total = fila['total_foreign']
        moneda = fila['currency']
        tasas = _tasas_en(fila['date'], cache=cache)
        rate_usd = tasas.get('USD')
        rate_eur = tasas.get('EUR')
        if moneda == 'EUR':
            eur = total
            bs = fila['total_bs']
            usd = (_redondear(total * fila['exchange_rate'] / rate_usd)
                   if rate_usd and fila.get('exchange_rate')
                   else Decimal('0.00'))
        elif moneda == 'BS':
            bs = total
            usd = (_redondear(total / rate_usd) if rate_usd
                   else Decimal('0.00'))
            eur = (_redondear(usd * rate_usd / rate_eur)
                   if usd and rate_eur and rate_usd else Decimal('0.00'))
        else:
            usd = total
            bs = fila['total_bs']
            eur = (_redondear(usd * rate_usd / rate_eur)
                   if rate_eur and rate_usd else Decimal('0.00'))
        return usd, bs, eur
    return _agregar(filas, valor)


def _agregar_consumo(filas, cache):
    def valor(fila):
        usd, bs, eur = _costo_usd_bs_eur(fila['product_id'], fila['date'], cache)
        qty = fila['quantity']
        return _redondear(usd * qty), _redondear(bs * qty), _redondear(eur * qty)
    return _agregar(filas, valor)


def _agregar_mermas(filas, cache):
    def valor(fila):
        # El importe exacto de la línea ya está en subtotal_cost; recalcular
        # unitario × cantidad reintroduce redondeos distintos al total.
        usd = fila.get('subtotal_cost')
        if not usd:
            usd = _redondear(fila['unit_cost_usd'] * fila['quantity'])
        tasas = _tasas_en(fila['date'], cache=cache)
        rate_usd = tasas.get('USD')
        rate_eur = tasas.get('EUR')
        bs = _redondear(usd * rate_usd) if rate_usd else Decimal('0.00')
        eur = (_redondear(usd * rate_usd / rate_eur) if rate_eur and rate_usd else Decimal('0.00'))
        return usd, bs, eur
    return _agregar(filas, valor)


def _agregar_traslados(filas, cache):
    """Valoriza pérdidas en traslados usando el costo del LOTE EXACTO (metodo='lote').

    Si el lote no existe en compras, cae a última compra (comportamiento del motor
    de costos) y loggea warning.
    """
    def valor(fila):
        from app.inventory.services import product_cost_service
        product_id = fila['product_id']
        lot_number = fila.get('lot_number')
        fecha = fila['date']
        qty = fila['quantity']

        unit_usd = product_cost_service.obtener_costo_unitario(
            product_id,
            fecha=fecha,
            moneda='USD',
            metodo='lote' if lot_number else 'ultima',
            lote=lot_number,
        )
        tasas = _tasas_en(fecha, cache=cache)
        rate_usd = tasas.get('USD')
        rate_eur = tasas.get('EUR')
        usd = _redondear(unit_usd * qty)
        bs = _redondear(usd * rate_usd) if rate_usd else Decimal('0.00')
        eur = (_redondear(usd * rate_usd / rate_eur) if rate_eur and rate_usd else Decimal('0.00'))
        return usd, bs, eur
    return _agregar(filas, valor)


def generar_snapshots(period_type=SnapshotPeriodType.MONTHLY, user_id=None, corte=None):
    """Reconstruye (UPSERT) los snapshots de los últimos 13 períodos."""
    if period_type not in PERIOD_TYPES:
        period_type = SnapshotPeriodType.MONTHLY
    ventana = periodos_historia(period_type, limite=13, corte=corte)
    return _generar_snapshots_ventana(ventana, period_type, user_id)


def generar_snapshot_periodo(period_type, inicio, fin, user_id=None):
    """Genera snapshots para UN solo período (inicio, fin)."""
    return _generar_snapshots_ventana([(inicio, fin)], period_type, user_id)


def _generar_snapshots_ventana(ventana, period_type, user_id, chunk_size=50):
    """Genera snapshots para una lista de (inicio, fin) en chunks para evitar timeout."""
    cache_tasas = {}
    totales = 0
    try:
        # Procesar en chunks para evitar timeout en datasets grandes
        for i in range(0, len(ventana), chunk_size):
            chunk = ventana[i:i + chunk_size]
            for inicio, fin in chunk:
                repo.guardar_snapshots(
                    SnapshotMetric.PURCHASES, period_type, inicio, fin,
                    _agregar_compras(repo.filas_compras(inicio, fin), cache_tasas),
                    user_id=user_id,
                )
                repo.guardar_snapshots(
                    SnapshotMetric.KITCHEN_CONSUMPTION, period_type, inicio, fin,
                    _agregar_consumo(repo.filas_consumo_cocina(inicio, fin), cache_tasas),
                    user_id=user_id,
                )
                repo.guardar_snapshots(
                    SnapshotMetric.WASTE, period_type, inicio, fin,
                    _agregar_mermas(repo.filas_mermas(inicio, fin), cache_tasas),
                    user_id=user_id,
                )
                repo.guardar_snapshots(
                    SnapshotMetric.TRANSFERS, period_type, inicio, fin,
                    _agregar_traslados(repo.filas_traslados(inicio, fin), cache_tasas),
                    user_id=user_id,
                )
                totales += 4
            # Commit por chunk para liberar memoria y evitar lock largo
            db.session.commit()
        return {'success': True, 'message': 'Snapshots actualizados.', 'períodos': len(ventana), 'registros': totales}
    except Exception as exc:
        logger.exception("Error al generar los snapshots de la ventana")
        db.session.rollback()
        return {'success': False, 'message': 'No se pudieron generar los snapshots. Intenta de nuevo.'}


def _actividad_por_metrica(inicio, fin, location_ids=None):
    """Último instante con hechos del período por (métrica, sede).

    Un snapshot puede existir y aun así estar viejo: el consumo de cocina se
    registra durante todo el período y las mermas se aprueban días después de
    registrarse (Waste.approved_at). Comparar la existencia de filas no basta
    para saber si el resumen refleja lo que ya está en las tablas fuente.
    """
    desde = datetime.combine(inicio, time.min)
    hasta = datetime.combine(fin, time.max)
    actividad = {}

    central = repo.sede_central()
    if central and (not location_ids or central in location_ids):
        ultima_compra = db.session.query(
            func.max(Purchase.purchase_date),
        ).filter(
            Purchase.status.in_(['COMPLETED', 'COMPLETADO']),
            Purchase.purchase_date >= desde,
            Purchase.purchase_date <= hasta,
        ).scalar()
        if ultima_compra is not None:
            actividad[(SnapshotMetric.PURCHASES, central)] = ultima_compra

    consulta = db.session.query(
        AuditLog.location_id, func.max(AuditLog.timestamp),
    ).filter(
        AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
        AuditLog.timestamp >= desde,
        AuditLog.timestamp <= hasta,
    )
    if location_ids:
        consulta = consulta.filter(AuditLog.location_id.in_(location_ids))
    for loc_id, ultimo in consulta.group_by(AuditLog.location_id).all():
        if loc_id and ultimo is not None:
            actividad[(SnapshotMetric.KITCHEN_CONSUMPTION, loc_id)] = ultimo

    # Solo las mermas que impactan el cajón (aprobadas o parciales) y las que
    # dejaron de impactarlo por cancelación/reversión. Una merma PENDIENTE no
    # debe forzar una regeneración en cada carga.
    consulta = db.session.query(
        Waste.location_id,
        func.max(Waste.date),
        func.max(Waste.approved_at),
        func.max(Waste.cancelled_at),
        func.max(Waste.reverted_at),
    ).filter(
        Waste.date >= desde,
        Waste.date <= hasta,
        or_(Waste.status.in_(['APROBADO', 'APROBADO_PARCIAL']),
            Waste.cancelled_at.isnot(None),
            Waste.reverted_at.isnot(None)),
    )
    if location_ids:
        consulta = consulta.filter(Waste.location_id.in_(location_ids))
    for fila in consulta.group_by(Waste.location_id).all():
        loc_id, *instantes = fila
        ultimo = max((i for i in instantes if i is not None), default=None)
        if loc_id and ultimo is not None:
            actividad[(SnapshotMetric.WASTE, loc_id)] = ultimo

    consulta = db.session.query(
        Movement.origin_location_id, func.max(Movement.date),
    ).filter(
        Movement.type == 'TRASLADO',
        Movement.status.notin_(['CANCELADO', 'CANCELADO_EMISOR', 'ANULADO',
                                'RECHAZADO']),
        Movement.date >= desde,
        Movement.date <= hasta,
    )
    if location_ids:
        consulta = consulta.filter(Movement.origin_location_id.in_(location_ids))
    for loc_id, ultimo in consulta.group_by(Movement.origin_location_id).all():
        if loc_id and ultimo is not None:
            actividad[(SnapshotMetric.TRANSFERS, loc_id)] = ultimo

    return actividad


def _periodo_desactualizado(period_type, inicio, fin, location_ids=None):
    """¿El período necesita regenerar sus snapshots?

    Sí cuando hay hechos en las tablas fuente para una (métrica, sede) que no
    tienen snapshot o cuyo snapshot se calculó ANTES del último hecho. Así el
    consumo y las mermas registrados después de la primera carga del panel no
    quedan congelados en cero para siempre.
    """
    consulta = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start == inicio,
    )
    if location_ids:
        consulta = consulta.filter(
            StatisticsSnapshot.location_id.in_(location_ids))

    # calculated_at se guarda en UTC naive (default del modelo) y las tablas
    # fuente usan el reloj de Venezuela; se comparan ambos en UTC.
    calculado = {}
    for snap in consulta.all():
        clave = (snap.metric, snap.location_id)
        instante = snap.calculated_at
        previo = calculado.get(clave)
        if previo is None or (instante is not None and instante < previo):
            calculado[clave] = instante

    for clave, ultima in _actividad_por_metrica(inicio, fin,
                                                location_ids).items():
        if ultima is None:
            continue
        instante = calculado.get(clave)
        if instante is None or instante < ve_a_utc(ultima):
            return True
    return False


def faltan_snapshots(period_type=SnapshotPeriodType.MONTHLY, corte=None, location_ids=None):
    """¿Falta el snapshot del período vigente para alguna sede?

    Se usa para la regeneración perezosa: el dashboard del Admin detecta si
    no existe el snapshot del período actual y lo genera antes de renderizar
    (el botón "Regenerar snapshots" queda como respaldo manual).

    Si se pasa location_ids, verifica solo esas sedes.
    """
    if period_type not in PERIOD_TYPES:
        period_type = SnapshotPeriodType.MONTHLY
    inicio, _ = calcular_periodo(period_type, corte)
    query = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start == inicio,
    )
    if location_ids:
        query = query.filter(StatisticsSnapshot.location_id.in_(location_ids))
    return query.first() is None


def asegurar_ventana_alarmas(period_type=SnapshotPeriodType.MONTHLY,
                            corte=None, user_id=None, location_ids=None,
                            limite=4):
    """Garantiza snapshots frescos para el gráfico y las alarmas.

    La alarma compara el período actual contra los 3 anteriores y el gráfico de
    evolución dibuja los últimos `PERIODOS_GRAFICO` períodos. El dashboard del
    Admin llama a esta función en cada carga para que los cuatro indicadores
    tengan montos por período.

    Antes bastaba con que existiera CUALQUIER fila del período para no volver a
    calcular. Eso dejaba a «Consumo Cocina» y «Mermas» en cero: se registran
    consumos y se aprueban mermas después de la primera carga, pero el snapshot
    del período ya existía (aunque fuera por Compras) y nunca se refrescaba.
    Ahora se recalcula únicamente cada período que tenga hechos más recientes
    que su snapshot (o que no tenga snapshot para una métrica con datos).
    """
    if period_type not in PERIOD_TYPES:
        period_type = SnapshotPeriodType.MONTHLY
    ventana = periodos_historia(period_type, limite=limite, corte=corte)
    pendientes = [
        (inicio, fin) for inicio, fin in ventana
        if _periodo_desactualizado(period_type, inicio, fin, location_ids)
    ]
    if not pendientes:
        return {'success': True, 'generados': 0}
    resultado = _generar_snapshots_ventana(pendientes, period_type, user_id)
    resultado['generados'] = len(pendientes)
    return resultado


def leer_configuracion():
    valores = {p.key: p.value for p in AppParameter.query.all()}
    return {
        'ESTADISTICAS_FACTOR': valores.get('ESTADISTICAS_FACTOR', str(FACTOR_DEFECTO)),
        'ESTADISTICAS_MINIMO_USD': valores.get('ESTADISTICAS_MINIMO_USD', str(MINIMO_DEFECTO)),
        'ESTADISTICAS_MONEDA': valores.get('ESTADISTICAS_MONEDA', 'USD'),
    }


def actualizar_configuracion(data):
    """Valida (en app.analytics.requests) y guarda los parámetros del cajón."""
    resultado = validate_config_payload(data)
    if not resultado['is_valid']:
        return resultado['errors']

    _set_parametro('ESTADISTICAS_FACTOR', resultado['factor'],
                   'Factor de disparo de alarmas de estadísticas (multiplica el promedio).')
    _set_parametro('ESTADISTICAS_MINIMO_USD', resultado['minimo_usd'],
                   'Mínimo en USD para considerar una alarma de estadísticas.')
    _set_parametro('ESTADISTICAS_MONEDA', resultado['moneda'],
                   'Moneda por defecto con la que abren los reportes de estadísticas.')
    db.session.commit()
    return {}


def _set_parametro(key, value, descripcion=None):
    parametro = AppParameter.query.filter_by(key=key).first()
    if parametro:
        parametro.value = str(value)
    else:
        parametro = AppParameter(key=key, value=str(value), description=descripcion)
        db.session.add(parametro)
    return parametro


def evaluar_alarmas(period_type=SnapshotPeriodType.MONTHLY, location_ids=None, crear_notificaciones=False):
    """Alarmas de irregularidad: valor del período actual > factor × promedio
    de los 3 períodos anteriores (siempre que el promedio sea > 0 y el valor
    alcance el mínimo configurado, en USD).

    Si `crear_notificaciones=True`, crea registros Notification tipo ALERTA_ESTADISTICA
    para los usuarios que tienen acceso a la sede correspondiente.
    """
    config = leer_configuracion()
    factor = Decimal(config['ESTADISTICAS_FACTOR'])
    minimo = Decimal(config['ESTADISTICAS_MINIMO_USD'])

    ventana = periodos_historia(period_type, limite=4)
    actual = ventana[-1]
    previos = ventana[:-1]
    inicio_actual = actual[0]

    snapshots = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start.in_([p[0] for p in ventana]),
    ).all()
    if location_ids:
        snapshots = [s for s in snapshots if s.location_id in location_ids]

    por_sede_metrica = {}
    for s in snapshots:
        clave = (s.location_id, s.metric)
        por_sede_metrica.setdefault(clave, {})
        por_sede_metrica[clave][s.period_start] = Decimal(str(s.amount_usd or 0))

    ubicaciones = {loc.id: loc.name for loc in Location.query.all()}
    etiquetas = {
        SnapshotMetric.PURCHASES: 'Compras',
        SnapshotMetric.KITCHEN_CONSUMPTION: 'Consumo Cocina',
        SnapshotMetric.WASTE: 'Mermas',
        SnapshotMetric.TRANSFERS: 'Traslados',
    }

    alertas = []
    alertas_para_notificar = []  # (loc_id, metric, alerta_dict)

    for (loc_id, metric), por_periodo in por_sede_metrica.items():
        valor = por_periodo.get(inicio_actual, Decimal('0'))
        # Solo promediar períodos que tengan datos reales (amount_usd > 0)
        # para no diluir el promedio con ceros de períodos sin actividad.
        prevs_con_datos = [
            por_periodo[p[0]]
            for p in previos
            if p[0] in por_periodo and por_periodo[p[0]] > 0
        ]
        if not prevs_con_datos:
            continue  # Sin histórico válido, no se puede evaluar
        promedio = sum(prevs_con_datos, Decimal('0')) / Decimal(len(prevs_con_datos))
        if promedio <= 0 or valor < minimo:
            continue
        if valor > factor * promedio:
            variacion = ((valor / promedio) - 1) * 100 if promedio else Decimal('0')
            alerta = {
                'metric': metric,
                'metric_label': etiquetas.get(metric, metric),
                'location_id': loc_id,
                'location_name': ubicaciones.get(loc_id, f'ID {loc_id}'),
                'valor_usd': valor,
                'promedio_usd': promedio,
                'variacion_pct': _redondear(variacion),
            }
            alertas.append(alerta)
            alertas_para_notificar.append((loc_id, metric, alerta))

    # Crear notificaciones si se solicita
    if crear_notificaciones and alertas_para_notificar:
        _crear_notificaciones_alarmas(alertas_para_notificar, period_type, inicio_actual)

    alertas.sort(key=lambda a: (a['metric'], a['location_id']))
    return alertas


def _crear_notificaciones_alarmas(alertas_para_notificar, period_type, period_start):
    """Crea notificaciones ALERTA_ESTADISTICA para usuarios con acceso a la sede.

    - Admin: recibe todas las alarmas
    - Finance: solo alarmas de sus sedes asignadas
    - Otros roles operativos: solo sus sedes (consistente con dashboard)
    """
    from app.models import User, Notification

    etiquetas_metrica = {
        SnapshotMetric.PURCHASES: 'Compras',
        SnapshotMetric.KITCHEN_CONSUMPTION: 'Consumo Cocina',
        SnapshotMetric.WASTE: 'Mermas',
        SnapshotMetric.TRANSFERS: 'Traslados',
    }

    etiquetas_periodo = {
        SnapshotPeriodType.WEEKLY: 'semanal',
        SnapshotPeriodType.MONTHLY: 'mensual',
        SnapshotPeriodType.QUARTERLY: 'trimestral',
        SnapshotPeriodType.ANNUAL: 'anual',
    }

    # Obtener todos los usuarios activos con roles que ven alarmas
    usuarios = User.query.filter(User.is_active == True).all()

    notificaciones_creadas = 0

    for user in usuarios:
        # Determinar sedes que ve el usuario
        if user.is_admin:
            sedes_usuario = None  # None = todas
        elif user.is_finance:
            sedes_usuario = [loc.id for loc in user.locations if loc.is_active]
            if not sedes_usuario:
                continue
        elif user.is_management or user.is_manager or user.is_assistant_manager or user.is_operations:
            sedes_usuario = [loc.id for loc in user.locations if loc.is_active]
            if not sedes_usuario:
                continue
        else:
            continue  # Otros roles no ven alarmas estadísticas

        # Filtrar alertas que corresponden a las sedes del usuario
        for loc_id, metric, alerta in alertas_para_notificar:
            if sedes_usuario is not None and loc_id not in sedes_usuario:
                continue

            # Evitar duplicados: usamos movement_id codificado (metric * 100000 + loc_id)
            # como clave única junto con user_id y type.
            # El multiplicador 100000 evita colisiones con IDs reales de Movement (asumimos < 100000).
            metric_value_map = {
                SnapshotMetric.PURCHASES: 1,
                SnapshotMetric.KITCHEN_CONSUMPTION: 2,
                SnapshotMetric.WASTE: 3,
                SnapshotMetric.TRANSFERS: 4,
            }
            movement_id_encoded = metric_value_map.get(metric, 0) * 100000 + loc_id

            existing = Notification.query.filter_by(
                user_id=user.id,
                type='ALERTA_ESTADISTICA',
                movement_id=movement_id_encoded
            ).first()

            if existing:
                continue  # Ya existe notificación para esta métrica/sede/usuario

            # Crear mensaje con enlace a estadísticas
            metric_label = etiquetas_metrica.get(metric, metric)
            periodo_label = etiquetas_periodo.get(period_type, period_type)
            message = (
                f"⚠️ Alarma estadística: {metric_label} en {alerta['location_name']} "
                f"({periodo_label} {period_start.strftime('%d/%m/%Y')}). "
                f"Valor: {float(alerta['valor_usd']):,.2f} USD, "
                f"Promedio 3 prev: {float(alerta['promedio_usd']):,.2f} USD "
                f"(+{alerta['variacion_pct']}%)."
            )

            notif = Notification(
                user_id=user.id,
                location_id=loc_id,
                type='ALERTA_ESTADISTICA',
                message=message[:255],
                is_read=False,
                movement_id=movement_id_encoded,
                waste_id=None,
                created_at=current_ve_time(),
            )
            db.session.add(notif)
            notificaciones_creadas += 1

    # Commit único fuera del loop para evitar commits parciales
    if notificaciones_creadas > 0:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception("No se pudieron guardar las notificaciones de alarmas")


def obtener_grafico_evolucion(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                              moneda='USD', location_ids=None):
    """Evolución de las 4 métricas por período, en la moneda pedida."""
    if moneda.upper() == 'BS':
        campo = 'amount_bs'
    elif moneda.upper() == 'EUR':
        campo = 'amount_eur'
    else:
        campo = 'amount_usd'

    periodos = periodos_historia(period_type, limite=PERIODOS_GRAFICO,
                                 corte=corte)
    claves = [p[0] for p in periodos]
    snapshots = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start.in_(claves),
        StatisticsSnapshot.metric.in_(METRICAS),
    ).all()
    if location_ids:
        snapshots = [s for s in snapshots if s.location_id in location_ids]

    por_metrica_periodo = {}
    for s in snapshots:
        por_metrica_periodo.setdefault(s.metric, {}).setdefault(s.period_start, Decimal('0'))
        por_metrica_periodo[s.metric][s.period_start] += Decimal(str(getattr(s, campo) or 0))

    def serie(metric):
        return [float(por_metrica_periodo.get(metric, {}).get(p[0], Decimal('0'))) for p in periodos]

    return {
        'period_type': period_type,
        'moneda': moneda.upper(),
        'periods': [
            {'start': p[0].isoformat(), 'label': _etiqueta_periodo(period_type, p[0])}
            for p in periodos
        ],
        'metrics': {
            SnapshotMetric.PURCHASES: serie(SnapshotMetric.PURCHASES),
            SnapshotMetric.KITCHEN_CONSUMPTION: serie(SnapshotMetric.KITCHEN_CONSUMPTION),
            SnapshotMetric.WASTE: serie(SnapshotMetric.WASTE),
            SnapshotMetric.TRANSFERS: serie(SnapshotMetric.TRANSFERS),
        },
    }


def obtener_ultimo_periodo(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                           moneda='USD', location_ids=None):
    """Resumen del período más reciente: {metric: {monto, cantidad}}."""
    campo = 'amount_bs' if moneda.upper() == 'BS' else (
        'amount_eur' if moneda.upper() == 'EUR' else 'amount_usd')
    inicio, _ = calcular_periodo(period_type, corte)
    consulta = StatisticsSnapshot.query.filter_by(
        period_type=period_type, period_start=inicio,
    )
    if location_ids:
        consulta = consulta.filter(StatisticsSnapshot.location_id.in_(location_ids))
    resumen = {}
    for s in consulta.all():
        resumen.setdefault(s.metric, {'monto': Decimal('0.00'), 'cantidad': Decimal('0.00')})
        resumen[s.metric]['monto'] += Decimal(str(getattr(s, campo) or 0))
        resumen[s.metric]['cantidad'] += Decimal(str(s.quantity or 0))
    return resumen


def obtener_costo_operativo(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                            moneda='USD', location_ids=None):
    """Egresos operativos del período (siempre en positivo).

    Delega en `consolidado_financiero` para usar la misma fórmula que
    Estadísticas y Finanzas: gastos de cocina + mermas + pérdidas de traslado.
    Las compras se informan aparte (`total_registrado`); no se restan.
    """
    from app.analytics.services.analysis_reports_service import (
        consolidado_financiero,
    )

    inicio, fin = calcular_periodo(period_type, corte)
    ids = location_ids or [loc.id for loc in Location.query.filter_by(
        is_active=True).all()]
    cero = Decimal('0.00')
    if not ids:
        return {
            'moneda': moneda.upper(), 'period_type': period_type,
            'period_start': inicio.isoformat(),
            'period_label': _etiqueta_periodo(period_type, inicio),
            'metricas': {m: cero for m in METRICAS},
            'compras': cero, 'consumo': cero, 'mermas': cero,
            'perdidas': cero, 'total': cero, 'total_registrado': cero,
            'por_concepto': [],
        }
    consolidado = consolidado_financiero(ids, inicio, fin, moneda,
                                          incluir_compras=True)
    conceptos = {f['concepto']: f['monto']
                 for f in consolidado['por_concepto']}
    consumo = conceptos.get('Gastos de cocina', cero)
    mermas = consolidado['mermas']
    perdidas = consolidado['perdidas_traslado']
    return {
        'moneda': consolidado['moneda'],
        'period_type': period_type,
        'period_start': inicio.isoformat(),
        'period_label': _etiqueta_periodo(period_type, inicio),
        'metricas': {
            SnapshotMetric.PURCHASES: consolidado['total_compras'],
            SnapshotMetric.KITCHEN_CONSUMPTION: consumo,
            SnapshotMetric.WASTE: mermas,
            SnapshotMetric.TRANSFERS: perdidas,
        },
        'compras': consolidado['total_compras'],
        'consumo': consumo,
        'mermas': mermas,
        'perdidas': perdidas,
        'total': consolidado['total_operativo'],
        'total_registrado': consolidado['total_registrado'],
        'por_concepto': consolidado['por_concepto'],
    }


def _campo_moneda(moneda):
    return 'amount_bs' if str(moneda).upper() == 'BS' else (
        'amount_eur' if str(moneda).upper() == 'EUR' else 'amount_usd')


def obtener_comparativo(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                        moneda='USD', location_ids=None):
    """Período actual vs el inmediatamente anterior (misma métrica y moneda).

    Devuelve {periodo_actual, periodo_anterior, metricas: {M: {actual, anterior,
    diff, variacion_pct}}}. Las sedes se suman (o se filtran con location_ids).
    """
    campo = _campo_moneda(moneda)
    ventana = periodos_historia(period_type, limite=2, corte=corte)
    anterior, actual = ventana

    consulta = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start.in_([actual[0], anterior[0]]),
    )
    if location_ids:
        consulta = consulta.filter(StatisticsSnapshot.location_id.in_(location_ids))

    por_periodo = {
        SnapshotMetric.PURCHASES: {actual[0]: Decimal('0.00'), anterior[0]: Decimal('0.00')},
        SnapshotMetric.KITCHEN_CONSUMPTION: {actual[0]: Decimal('0.00'), anterior[0]: Decimal('0.00')},
        SnapshotMetric.WASTE: {actual[0]: Decimal('0.00'), anterior[0]: Decimal('0.00')},
        SnapshotMetric.TRANSFERS: {actual[0]: Decimal('0.00'), anterior[0]: Decimal('0.00')},
    }
    for s in consulta.all():
        if s.metric in por_periodo and s.period_start in por_periodo[s.metric]:
            por_periodo[s.metric][s.period_start] += Decimal(str(getattr(s, campo) or 0))

    metricas = {}
    for metric, montos in por_periodo.items():
        valor_actual = montos[actual[0]]
        valor_anterior = montos[anterior[0]]
        diff = valor_actual - valor_anterior
        variacion = (((valor_actual / valor_anterior) - 1) * 100
                     if valor_anterior else None)
        metricas[metric] = {
            'actual': valor_actual,
            'anterior': valor_anterior,
            'diff': diff,
            'variacion_pct': (_redondear(variacion)
                              if variacion is not None else None),
        }
    return {
        'moneda': str(moneda).upper(),
        'period_type': period_type,
        'periodo_actual': _etiqueta_periodo(period_type, actual[0]),
        'periodo_anterior': _etiqueta_periodo(period_type, anterior[0]),
        'metricas': metricas,
    }


def obtener_ranking_sedes(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                          moneda='USD', location_ids=None):
    """Rankings entre sedes para el período más reciente.

    Devuelve rankings separados por métrica (como pide la propuesta):
    - gasto_total: compras + consumo (quién gasta más)
    - mermas_costo: costo de mermas (quién pierde más en mermas)
    - mermas_cantidad: cantidad de mermas
    - traslados: valor de traslados (quién genera más traslados)
    - perdidas_traslado: pérdidas en traslado (quién pierde más en traslados)
    - perdidas_traslado: pérdidas reales en traslado
    - costo_operativo: consumo + mermas + pérdidas (egresos positivos)

    Cada ranking incluye location_id, location_name, valor y posición.
    """
    campo = _campo_moneda(moneda)
    inicio, _ = calcular_periodo(period_type, corte)
    consulta = StatisticsSnapshot.query.filter_by(
        period_type=period_type, period_start=inicio,
    )
    if location_ids:
        consulta = consulta.filter(StatisticsSnapshot.location_id.in_(location_ids))

    por_sede = {}
    for s in consulta.all():
        sea = por_sede.setdefault(s.location_id, {
            'compras': Decimal('0.00'), 'consumo': Decimal('0.00'),
            'mermas': Decimal('0.00'), 'mermas_qty': Decimal('0.00'),
            'traslados': Decimal('0.00'),
        })
        valor = Decimal(str(getattr(s, campo) or 0))
        if s.metric == SnapshotMetric.PURCHASES:
            sea['compras'] += valor
        elif s.metric == SnapshotMetric.KITCHEN_CONSUMPTION:
            sea['consumo'] += valor
        elif s.metric == SnapshotMetric.WASTE:
            sea['mermas'] += valor
            sea['mermas_qty'] += Decimal(str(s.quantity or 0))
        elif s.metric == SnapshotMetric.TRANSFERS:
            sea['traslados'] += valor

    nombres = {loc.id: loc.name for loc in Location.query.all()}
    sedes = []
    for loc_id, datos in por_sede.items():
        datos['perdidas_traslado'] = datos['traslados']
        datos['costo_operativo'] = (
            datos['consumo'] + datos['mermas'] + datos['perdidas_traslado'])
        datos['gasto_total'] = datos['compras'] + datos['consumo']
        sedes.append({
            'location_id': loc_id,
            'location_name': nombres.get(loc_id, f'ID {loc_id}'),
            **datos,
        })

    # Rankings separados por métrica
    def _ranking(lista, key, reverse=True):
        ordenados = sorted(lista, key=lambda s: s.get(key, Decimal('0')), reverse=reverse)
        return [
            {'posicion': i + 1, 'location_id': s['location_id'],
             'location_name': s['location_name'], 'valor': s.get(key, Decimal('0'))}
            for i, s in enumerate(ordenados)
        ]

    rankings = {
        'gasto_total': _ranking(sedes, 'gasto_total'),
        'mermas_costo': _ranking(sedes, 'mermas'),
        'mermas_cantidad': _ranking(sedes, 'mermas_qty'),
        'traslados': _ranking(sedes, 'traslados'),
        'perdidas_traslado': _ranking(sedes, 'perdidas_traslado'),
        'costo_operativo': _ranking(sedes, 'costo_operativo'),
        'compras': _ranking(sedes, 'compras'),
    }

    return {
        'moneda': str(moneda).upper(),
        'period_type': period_type,
        'period_start': inicio.isoformat(),
        'period_label': _etiqueta_periodo(period_type, inicio),
        'rankings': rankings,
        'sedes': sedes,
    }


def obtener_mermas_por_tipo(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                            location_ids=None, moneda='USD'):
    """Costo y cantidad de mermas del período por tipo, en la moneda pedida.

    Misma fuente y criterios que el snapshot WASTE (filas_mermas): cabeceras
    APROBADO/PENDIENTE/APROBADO_PARCIAL (solo líneas APROBADO en las parciales),
    sin canceladas, valoradas con el costo en el detalle. Los tipos sin nombre
    se agrupan como 'Sin tipo'.

    NOTA: Esta función consulta directamente WasteDetail + WasteType porque el
    snapshot `StatisticsSnapshot` solo almacena el total agregado WASTE por
    sede/período (sin desglose por waste_type_id). El desglose por tipo de merma
    es una vista de detalle que requiere el JOIN a WasteType, por eso se consulta
    directamente la tabla fuente manteniendo los mismos criterios de filtrado
    que el snapshot (estados, canceladas, fechas).
    """
    import collections

    from app.models.waste_model import Waste, WasteDetail, WasteType

    moneda = (moneda or 'USD').upper()
    if moneda not in ('USD', 'BS', 'EUR'):
        moneda = 'USD'

    inicio, fin = calcular_periodo(period_type, corte)
    consulta = WasteDetail.query \
        .join(Waste, WasteDetail.waste_id == Waste.id) \
        .outerjoin(WasteType, WasteDetail.waste_type_id == WasteType.id) \
        .filter(
            Waste.status.in_(['APROBADO', 'PENDIENTE', 'APROBADO_PARCIAL']),
            Waste.cancelled_at.is_(None),
            Waste.date >= datetime.combine(inicio, time.min),
            Waste.date <= datetime.combine(fin, time.max),
        )
    if location_ids:
        consulta = consulta.filter(Waste.location_id.in_(location_ids))

    def convertir(usd, fecha, cache):
        if moneda == 'USD':
            return usd
        tasas = _tasas_en(fecha, cache=cache)
        rate_usd = tasas.get('USD')
        rate_eur = tasas.get('EUR')
        if moneda == 'BS':
            return _redondear(usd * rate_usd) if rate_usd else Decimal('0.00')
        return (_redondear(usd * rate_usd / rate_eur)
                if rate_usd and rate_eur else Decimal('0.00'))

    cache_tasas = {}
    grupos = collections.OrderedDict()
    for detalle in consulta.all():
        if not detalle.waste.location_id:
            continue
        if detalle.waste.status == 'APROBADO_PARCIAL' \
                and (detalle.status or '') != 'APROBADO':
            continue
        clave = detalle.waste_type_id
        if clave not in grupos:
            grupos[clave] = {
                'tipo': (detalle.waste_type.name if detalle.waste_type else 'Sin tipo'),
                'cantidad': Decimal('0.00'),
                'monto_usd': Decimal('0.00'),
                'monto': Decimal('0.00'),
            }
        usd = _redondear(
            Decimal(str(detalle.unit_cost or 0)) * Decimal(str(detalle.quantity or 0)))
        grupos[clave]['cantidad'] += Decimal(str(detalle.quantity or 0))
        grupos[clave]['monto_usd'] += usd
        grupos[clave]['monto'] += convertir(usd, detalle.waste.date, cache_tasas)

    por_tipo = sorted(grupos.values(),
                      key=lambda g: g['monto'], reverse=True)
    return {
        'moneda': moneda,
        'period_type': period_type,
        'period_start': inicio.isoformat(),
        'period_label': _etiqueta_periodo(period_type, inicio),
        'tipos': por_tipo,
    }


def obtener_pendientes():
    """Conteos para el bloque 'Pendientes por Atender' del dashboard Admin."""
    mermas = Waste.query.filter(Waste.status == 'PENDIENTE', Waste.cancelled_at.is_(None)).count()
    transito = Movement.query.filter_by(status='EN_TRANSITO').count()
    disputas = Movement.query.filter(Movement.status.in_(
        MovementDisputeRepository.PENDING_DISPUTE_STATUSES,
    )).count()
    return {
        'mermas_pendientes': mermas,
        'traslados_en_transito': transito,
        'disputas_pendientes': disputas,
    }


def obtener_flujo_traslados(period_type=SnapshotPeriodType.MONTHLY, moneda='USD',
                            location_ids=None, corte=None, limite=13):
    """Flujo REAL de traslados por período para el dashboard del Admin.

    A diferencia del snapshot TRANSFERS (que solo mide pérdidas en traslado),
    aquí se cuenta TODA la mercancía despachada y su costo (último costo de
    compra por producto/lote), reutilizando obtener_traslados_direccional del
    cajón de finanzas: {periods, serie: {cost, conteo, quantity}, comparativo}.
    Se usa el total despachado (no el recibido) porque el KPI mide mercancía
    movida/salida.
    """
    from app.analytics.services.analysis_reports_service import (
        obtener_traslados_direccional,
    )

    if not location_ids:
        location_ids = [loc.id for loc in Location.query.filter_by(is_active=True).all()]
    moneda = (moneda or 'USD').upper()

    periodos = periodos_historia(period_type, limite=limite, corte=corte)
    costos, conteos, cantidades = [], [], []
    for inicio, fin in periodos:
        flujo = obtener_traslados_direccional(location_ids, inicio, fin, moneda)
        total = flujo['total_despachado']
        costos.append(float(total['cost']))
        conteos.append(total['conteo'])
        cantidades.append(float(total['quantity']))

    comparativo = {
        'actual': Decimal('0.00'),
        'anterior': Decimal('0.00'),
        'diff': Decimal('0.00'),
        'variacion_pct': Decimal('0.00'),
    }
    if len(costos) >= 2:
        act, ant = Decimal(str(costos[-1])), Decimal(str(costos[-2]))
        comparativo = {
            'actual': act,
            'anterior': ant,
            'diff': act - ant,
            'variacion_pct': (_redondear(((act - ant) / ant) * 100) if ant
                              else Decimal('0.00')),
        }

    return {
        'period_type': period_type,
        'moneda': moneda,
        'periods': [
            {'start': p[0].isoformat(),
             'label': _etiqueta_periodo(period_type, p[0])}
            for p in periodos
        ],
        'serie': {
            'cost': costos,
            'conteo': conteos,
            'quantity': cantidades,
        },
        'comparativo': comparativo,
    }