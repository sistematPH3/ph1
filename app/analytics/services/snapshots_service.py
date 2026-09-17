"""Servicios del cajón de estadísticas (Rápido 1 - Módulo 8).

Orquesta la generación de snapshots (UPSERT idempotente), la evaluación de
alarmas de irregularidad, la configuración (factor y mínimo) y los datos que
consumen el dashboard del Admin y el panel /estadisticas.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.time_utils import current_ve_time
from app.models.statistics_model import SnapshotMetric, SnapshotPeriodType, StatisticsSnapshot
from app.models.waste_model import AppParameter, Waste
from app.models.logistics_model import Location, Movement
from app.analytics.repositories import snapshots_repository as repo
from app.analytics.requests.statistics_validators import validate_config_payload
from app.inventory.services import product_cost_service
from app.logistics.repositories.movement_dispute_repository import MovementDisputeRepository

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
    unit_eur = (_redondear(unit_usd * tasa_eur / tasa_usd)
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
    def valor(fila):
        qty = fila['quantity']
        if fila['currency'] == 'EUR':
            tasas = _tasas_en(fila['date'], cache=cache)
            rate_usd = tasas.get('USD')
            rate_eur = tasas.get('EUR')
            usd = _redondear(fila['unit_foreign'] * qty * rate_eur / rate_usd) if rate_usd and rate_eur else Decimal('0.00')
            eur = _redondear(fila['unit_foreign'] * qty)
        else:
            usd = _redondear(fila['unit_foreign'] * qty)
            tasas = _tasas_en(fila['date'], cache=cache)
            rate_usd = tasas.get('USD')
            rate_eur = tasas.get('EUR')
            eur = (_redondear(usd * rate_eur / rate_usd) if rate_eur and rate_usd else Decimal('0.00'))
        bs = _redondear(fila['price_bs'] * qty) if fila['price_bs'] else Decimal('0.00')
        if not bs and usd:
            tasas = _tasas_en(fila['date'], cache=cache)
            rate_usd = tasas.get('USD')
            bs = _redondear(usd * rate_usd) if rate_usd else Decimal('0.00')
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
        usd = _redondear(fila['unit_cost_usd'] * fila['quantity'])
        tasas = _tasas_en(fila['date'], cache=cache)
        rate_usd = tasas.get('USD')
        rate_eur = tasas.get('EUR')
        bs = _redondear(usd * rate_usd) if rate_usd else Decimal('0.00')
        eur = (_redondear(usd * rate_eur / rate_usd) if rate_eur and rate_usd else Decimal('0.00'))
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
        eur = (_redondear(usd * rate_eur / rate_usd) if rate_eur and rate_usd else Decimal('0.00'))
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


def _generar_snapshots_ventana(ventana, period_type, user_id):
    """Genera snapshots para una lista de (inicio, fin)."""
    cache_tasas = {}
    totales = 0
    try:
        for inicio, fin in ventana:
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
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': f'Error al generar snapshots: {exc}'}
    return {'success': True, 'message': 'Snapshots actualizados.', 'períodos': len(ventana), 'registros': totales}


def faltan_snapshots(period_type=SnapshotPeriodType.MONTHLY, corte=None):
    """¿Falta el snapshot del período vigente?

    Se usa para la regeneración perezosa: el dashboard del Admin detecta si
    no existe el snapshot del período actual y lo genera antes de renderizar
    (el botón "Regenerar snapshots" queda como respaldo manual).
    """
    if period_type not in PERIOD_TYPES:
        period_type = SnapshotPeriodType.MONTHLY
    inicio, _ = calcular_periodo(period_type, corte)
    return StatisticsSnapshot.query.filter(
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start == inicio,
    ).first() is None


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


def evaluar_alarmas(period_type=SnapshotPeriodType.MONTHLY, location_ids=None):
    """Alarmas de irregularidad: valor del período actual > factor × promedio
    de los 3 períodos anteriores (siempre que el promedio sea > 0 y el valor
    alcance el mínimo configurado, en USD)."""
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
            alertas.append({
                'metric': metric,
                'metric_label': etiquetas.get(metric, metric),
                'location_id': loc_id,
                'location_name': ubicaciones.get(loc_id, f'ID {loc_id}'),
                'valor_usd': valor,
                'promedio_usd': promedio,
                'variacion_pct': _redondear(variacion),
            })
    alertas.sort(key=lambda a: (a['metric'], a['location_id']))
    return alertas


def obtener_grafico_evolucion(period_type=SnapshotPeriodType.MONTHLY, corte=None,
                              moneda='USD', location_ids=None):
    """Evolución de las 4 métricas por período, en la moneda pedida."""
    if moneda.upper() == 'BS':
        campo = 'amount_bs'
    elif moneda.upper() == 'EUR':
        campo = 'amount_eur'
    else:
        campo = 'amount_usd'

    periodos = periodos_historia(period_type, corte=corte)
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
    """Costo operativo del período más reciente, fórmula literal de la propuesta:

        Compras − consumo cocina − mermas − pérdidas en traslado

    Devuelve el desglose por métrica y el total, en la moneda pedida.
    """
    campo = 'amount_bs' if moneda.upper() == 'BS' else (
        'amount_eur' if moneda.upper() == 'EUR' else 'amount_usd')
    inicio, _ = calcular_periodo(period_type, corte)
    consulta = StatisticsSnapshot.query.filter_by(
        period_type=period_type, period_start=inicio,
    )
    if location_ids:
        consulta = consulta.filter(StatisticsSnapshot.location_id.in_(location_ids))
    totales = {'PURCHASES': Decimal('0.00'), 'KITCHEN_CONSUMPTION': Decimal('0.00'),
               'WASTE': Decimal('0.00'), 'TRANSFERS': Decimal('0.00')}
    for s in consulta.all():
        if s.metric in totales:
            totales[s.metric] += Decimal(str(getattr(s, campo) or 0))
    operativo = (
        totales['PURCHASES'] - totales['KITCHEN_CONSUMPTION']
        - totales['WASTE'] - totales['TRANSFERS']
    )
    return {
        'moneda': moneda.upper(),
        'period_type': period_type,
        'period_start': inicio.isoformat(),
        'period_label': _etiqueta_periodo(period_type, inicio),
        'metricas': totales,
        'compras': totales['PURCHASES'],
        'consumo': totales['KITCHEN_CONSUMPTION'],
        'mermas': totales['WASTE'],
        'perdidas': totales['TRANSFERS'],
        'total': operativo,
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
                     if valor_anterior else Decimal('0.00'))
        metricas[metric] = {
            'actual': valor_actual,
            'anterior': valor_anterior,
            'diff': diff,
            'variacion_pct': _redondear(variacion),
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
    - costo_operativo: compras - consumo - mermas - traslados

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
        datos['costo_operativo'] = (
            datos['compras'] - datos['consumo'] - datos['mermas'] - datos['traslados'])
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
        'perdidas_traslado': _ranking(sedes, 'traslados'),
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
                            location_ids=None):
    """Costo y cantidad de mermas del período por tipo, en USD (base del cajón).

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
            }
        grupos[clave]['cantidad'] += Decimal(str(detalle.quantity or 0))
        grupos[clave]['monto_usd'] += _redondear(
            Decimal(str(detalle.unit_cost or 0)) * Decimal(str(detalle.quantity or 0)))

    por_tipo = sorted(grupos.values(),
                      key=lambda g: g['monto_usd'], reverse=True)
    return {
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