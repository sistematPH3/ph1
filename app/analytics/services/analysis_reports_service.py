from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.time_utils import current_ve_time
from app.analytics.repositories.analysis_reports_repository import (
    ESTADOS_TRASLADO_EN_TRANSITO,
    fechas_con_registros,
    hay_snapshots_metrico,
    listar_periodos_disponibles,
    obtener_compras_consolidado,
    obtener_compras_por_moneda,
    obtener_compras_por_proveedor,
    obtener_consumo_valorizado,
    obtener_devoluciones_central,
    obtener_gasto_por_categoria,
    obtener_mermas_detalle,
    obtener_mermas_resumen,
    obtener_mermas_top_producto,
    obtener_nombres_sedes,
    obtener_recibido_por_insumo,
    obtener_resumen_consumo,
    obtener_resumen_traslados,
    obtener_sedes_permitidas,
    obtener_snapshot,
    obtener_snapshot_por_periodo,
    obtener_tasa_historica,
    obtener_totales_reales,
    obtener_traslados_valorizados,
)

MONEDAS = ('USD', 'BS', 'EUR')

SEDE_CENTRAL_ID = 1


def _orientacion_efectiva(location_ids, incluir_compras):
    """Sede desde la que se narran los traslados según el ámbito consultado.
    Cuando la consulta es una sola sede, el flujo se narra desde ELLA (la
    Central 'envía', una sede común 'recibe'); cuando abarca varias sedes, se
    narra desde la Central para quien la gestiona (todo lo que despacha) y
    relativo a sus sedes para el resto."""
    if location_ids is None:
        return None
    if len(location_ids) == 1:
        return location_ids[0]
    return SEDE_CENTRAL_ID if incluir_compras else None


def flujo_recibido_por_destino(direccional):
    """Mercancía que llegó a las sedes visibles: recibidos + internos.

    En un ámbito multi-sede los movimientos entre las sedes del propio
    usuario se clasifican como 'internos', pero también llegaron a una sede
    visible. Se suman a 'recibidos' para no reportar 0 (misma regla que la
    sección 'Mercancía recibida': se mide por sede de destino).
    """
    return {
        'conteo': (direccional['recibidos']['conteo']
                   + direccional['internos']['conteo']),
        'quantity': (direccional['recibidos']['quantity']
                     + direccional['internos']['quantity']),
        'cost': (direccional['recibidos']['cost']
                 + direccional['internos']['cost']),
    }


def usuario_administra_central(user_id):
    """True si el usuario gestiona la sede Central (id 1). Solo quien la maneja
    ve las compras: el admin las ve todas; el resto solo si tiene la Central
    entre sus sedes asignadas activas."""
    from app.extensions import db
    from app.models.security_model import User
    user = db.session.get(User, user_id) if user_id is not None else None
    if user is None:
        return False
    if user.is_admin:
        return True
    return any(loc.is_active and loc.id == SEDE_CENTRAL_ID
               for loc in user.locations)


def aplica_compras(user_id, location_ids):
    """Las compras solo ocurren en la sede Central, así que se incluyen cuando
    el usuario la gestiona Y la sede consultada la contiene."""
    if not location_ids:
        return False
    return usuario_administra_central(user_id) and SEDE_CENTRAL_ID in location_ids


def aplica_compras_por_filtro(user_id, location_id=None):
    """Versión de aplica_compras para el filtro en crudo: con location_id None
    se ve toda la empresa (incluye la Central); con una sede concreta, solo si
    es la Central."""
    if not usuario_administra_central(user_id):
        return False
    if location_id in (None, ''):
        return True
    try:
        return int(location_id) == SEDE_CENTRAL_ID
    except (TypeError, ValueError):
        return False


def _tasa(moneda, fecha):
    """Tasa BCV (Bs por unidad) vigente en 'fecha': el último registro de
    ExchangeRateHistory con timestamp <= fecha. None si no hay."""
    if fecha is None:
        return None
    return obtener_tasa_historica(moneda, fecha)


_ALIAS_BOLIVARES = ('VES', 'BS.', 'BSS', 'BOLIVARES', 'BOLÍVARES')


def _moneda_normalizada(codigo):
    """Homologa el código de moneda a MONEDAS: los registros viejos guardan los
    bolívares como 'VES', 'BSS' o 'BS.' y sin esto se valoraban en 0."""
    codigo = (codigo or 'USD').upper()
    return 'BS' if codigo in _ALIAS_BOLIVARES else codigo


def _convertir_monto(monto, origen, destino, fecha):
    """Convierte 'monto' de su moneda de origen a la del reporte con la tasa
    BCV vigente en 'fecha'. Retorna None si la tasa necesaria no existe
    (por ejemplo, EUR cuando no se han cargado tasas EUR)."""
    monto = Decimal(str(monto or 0))
    if not monto:
        return Decimal('0.00')
    origen = _moneda_normalizada(origen)
    destino = _moneda_normalizada(destino)
    if origen == destino:
        return monto
    if origen not in MONEDAS or destino not in MONEDAS:
        return None
    try:
        if origen == 'USD' and destino == 'BS':
            tasa = _tasa('USD', fecha)
            return monto * tasa if tasa else None
        if origen == 'BS' and destino == 'USD':
            tasa = _tasa('USD', fecha)
            return monto / tasa if tasa else None
        if origen == 'EUR' and destino == 'BS':
            tasa = _tasa('EUR', fecha)
            return monto * tasa if tasa else None
        if origen == 'BS' and destino == 'EUR':
            tasa = _tasa('EUR', fecha)
            return monto / tasa if tasa else None
        if origen == 'USD' and destino == 'EUR':
            tasa_usd, tasa_eur = _tasa('USD', fecha), _tasa('EUR', fecha)
            return monto * tasa_usd / tasa_eur if tasa_usd and tasa_eur else None
        if origen == 'EUR' and destino == 'USD':
            tasa_usd, tasa_eur = _tasa('USD', fecha), _tasa('EUR', fecha)
            return monto * tasa_eur / tasa_usd if tasa_usd and tasa_eur else None
    except (TypeError, ZeroDivisionError):
        return None
    return None


def _convertir_buckets(buckets, destino, fecha):
    """Suma los montos en USD/BS/EUR del dict convirtiendo cada uno a la moneda
    del reporte. Los componentes en cero no exigen tasa; si una moneda con
    monto no tiene tasa se omite solo esa porción, en lugar de anular todo el
    total (una serie EUR incompleta ya no borra los montos en Bs/USD)."""
    total = Decimal('0.00')
    for moneda in MONEDAS:
        monto = buckets.get(moneda, Decimal('0.00')) or Decimal('0.00')
        if not monto:
            continue
        convertido = _convertir_monto(monto, moneda, destino, fecha)
        if convertido is not None:
            total += convertido
    return total


def _monedas_sin_tasa(buckets_lista, destino, fecha):
    """Monedas con monto real que no se pudieron sumar al total por falta de
    tasa BCV. La UI las muestra: el total queda parcial en lugar de omitir esa
    porción en silencio."""
    destino = _moneda_normalizada(destino)
    faltan = set()
    for buckets in buckets_lista:
        for clave, valor in (buckets or {}).items():
            moneda = _moneda_normalizada(clave)
            monto = valor or Decimal('0.00')
            if not monto or moneda == destino or moneda not in MONEDAS:
                continue
            if _convertir_monto(monto, moneda, destino, fecha) is None:
                faltan.add(moneda)
    return sorted(faltan)


def _monto_en_moneda(buckets, moneda, fecha=None):
    """Monto de COMPRAS en la moneda del reporte usando el valor REGISTRADO:
    el BS de cada detalle quedó grabado en price_bs con la tasa del día de la
    compra (Purchase.exchange_rate), así que se muestra ese monto sin re-valuarlo
    con la tasa del cierre. Si la moneda elegida no tiene valor registrado, se
    convierte UNA sola fuente (el BS registrado, que existe para toda compra;
    si falta, la moneda original) para no sumar valoraciones paralelas del
    mismo gasto. Sin tasa disponible da 0.00."""
    moneda = _moneda_normalizada(moneda)
    buckets = buckets or {}
    registrado = buckets.get(moneda, Decimal('0.00')) or Decimal('0.00')
    if registrado:
        return _redondear(registrado)
    for origen in ('BS', 'USD', 'EUR'):
        monto = buckets.get(origen, Decimal('0.00')) or Decimal('0.00')
        if not monto:
            continue
        convertido = _convertir_monto(monto, origen, moneda, fecha)
        if convertido is not None:
            return _redondear(convertido)
    return Decimal('0.00')


def _convertir_compra_a_moneda(fila, moneda):
    """Equivalente de una compra a la moneda del reporte usando la tasa del día
    que el sistema registró (exchange_rate = Bs por unidad de la moneda de la
    compra). None si no hay tasa disponible (p. ej. EUR sin tasa cargada)."""
    # La moneda del registro se homologa ANTES de armar la clave: las compras
    # viejas guardan 'VES' y no existe la columna total_ves (sí total_bs), así
    # que se valoraban en 0 y desaparecían del panel "por moneda".
    c = _moneda_normalizada(fila.get('currency'))
    moneda = _moneda_normalizada(moneda)
    monto = fila.get('total_' + c.lower(), Decimal('0.00')) or Decimal('0.00')
    if not monto or c == moneda:
        return monto
    if c == 'BS' and moneda == 'EUR':
        # El monto está en Bs: se divide por la tasa BCV del EURO del día de
        # la compra, no por la tasa Bs/USD guardada en la compra. No depende
        # de exchange_rate: si falta, la tasa EUR del día sigue siendo válida.
        fecha = fila.get('purchase_date') or datetime.now()
        tasa_eur = obtener_tasa_historica('EUR', fecha)
        return monto / tasa_eur if tasa_eur else None
    tasa = Decimal(str(fila.get('exchange_rate') or 0))
    if not tasa:
        return None
    if c == 'USD' and moneda == 'BS':
        return monto * tasa
    if c == 'BS' and moneda == 'USD':
        return monto / tasa
    if c == 'EUR' and moneda == 'BS':
        return monto * tasa
    fecha = fila.get('purchase_date') or datetime.now()
    if c == 'USD' and moneda == 'EUR':
        # Triangulado vía Bs: la tasa guardada es Bs/USD; se divide por Bs/EUR.
        tasa_eur = obtener_tasa_historica('EUR', fecha)
        return monto * tasa / tasa_eur if tasa_eur else None
    if c == 'EUR' and moneda == 'USD':
        # Triangulado vía Bs: la tasa guardada es Bs/EUR; se divide por Bs/USD.
        tasa_usd = obtener_tasa_historica('USD', fecha)
        return monto * tasa / tasa_usd if tasa_usd else None
    return None


def _compras_en_moneda(desde_dt, hasta_dt, moneda):
    """Total de compras del rango en la moneda del reporte, compra por compra
    con la tasa del día de cada una. Es la base del concepto 'Compras' y de la
    estadística 'en qué moneda se compra más'."""
    total = Decimal('0.00')
    for fila in obtener_compras_por_moneda(desde_dt, hasta_dt):
        equiv = _convertir_compra_a_moneda(fila, moneda)
        total += equiv if equiv is not None else Decimal('0.00')
    return _redondear(total)


def _por_moneda_panel(desde_dt, hasta_dt, moneda):
    """Estadística de 'en qué moneda se compra más': por cada moneda (USD/BS/EUR)
    el total registrado en su propia moneda, la cantidad de compras y su
    equivalente en la moneda del reporte (con la tasa del día de compra)."""
    agregado = {}
    moneda = _moneda_normalizada(moneda)
    for fila in obtener_compras_por_moneda(desde_dt, hasta_dt):
        c = _moneda_normalizada(fila['currency'])
        ag = agregado.setdefault(c, {
            'monto': Decimal('0.00'),
            'equivalente': Decimal('0.00'),
            'compras': 0,
        })
        ag['monto'] += fila.get('total_' + c.lower(), Decimal('0.00')) or Decimal('0.00')
        ag['compras'] += 1
        equiv = _convertir_compra_a_moneda(fila, moneda)
        ag['equivalente'] += equiv if equiv is not None else Decimal('0.00')

    total_equiv = sum((ag['equivalente'] for ag in agregado.values()), Decimal('0.00'))
    filas = []
    for c in ('USD', 'BS', 'EUR'):
        ag = agregado.get(c)
        if ag is None or not ag['monto']:
            continue
        equivalente = _redondear(ag['equivalente'])
        filas.append({
            'currency': c,
            'monto': _redondear(ag['monto']),
            'compras': ag['compras'],
            'equivalente': equivalente,
            'pct': (_redondear((ag['equivalente'] / total_equiv) * 100)
                    if total_equiv else Decimal('0.00')),
        })
    return {
        'moneda': moneda,
        'filas': filas,
        'total': _redondear(total_equiv),
    }


def _bucket_vacio():
    return {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}


def _redondear(monto, digitos=2):
    if monto is None:
        return Decimal('0.00').quantize(Decimal('1.' + '0' * digitos))
    return Decimal(str(monto)).quantize(Decimal('1.' + '0' * digitos),
                                        rounding=ROUND_HALF_UP)


def _add_months(fecha, meses):
    indice = fecha.month - 1 + meses
    anio = fecha.year + indice // 12
    mes = indice % 12 + 1
    return fecha.replace(year=anio, month=mes, day=1)


def calcular_periodo(period_type, ref_date=None):
    """Rango [inicio, fin] del período que contiene a ref_date y el equivalente
    anterior, según el tipo de período."""
    ref = ref_date or current_ve_time().date()
    alias = {'SEMANAL': 'WEEKLY', 'MENSUAL': 'MONTHLY', 'TRIMESTRE': 'QUARTERLY',
             'ANUAL': 'ANNUAL'}
    ptype = alias.get((period_type or 'MONTHLY').upper(),
                      (period_type or 'MONTHLY').upper())

    if ptype == 'WEEKLY':
        inicio = ref - timedelta(days=ref.weekday())
        fin = inicio + timedelta(days=6)
        previo_inicio = inicio - timedelta(days=7)
    elif ptype == 'QUARTERLY':
        trimestre = (ref.month - 1) // 3
        inicio = ref.replace(year=ref.year, month=trimestre * 3 + 1, day=1)
        fin = _add_months(inicio, 3) - timedelta(days=1)
        previo_inicio = _add_months(inicio, -3)
    elif ptype == 'ANNUAL':
        inicio = ref.replace(month=1, day=1)
        fin = ref.replace(year=ref.year + 1, month=1, day=1) - timedelta(days=1)
        previo_inicio = inicio.replace(year=inicio.year - 1)
    else:
        inicio = ref.replace(day=1)
        fin = _add_months(inicio, 1) - timedelta(days=1)
        previo_inicio = _add_months(inicio, -1)

    previo_fin = inicio - timedelta(days=1)

    return {
        'period_type': ptype,
        'period_start': inicio,
        'period_end': fin,
        'previous_start': previo_inicio,
        'previous_end': previo_fin,
        'label': _etiqueta_periodo(ptype, inicio, fin),
    }


def _etiqueta_periodo(period_type, inicio, fin):
    nombres_mes = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                   'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre',
                   'Diciembre']
    if period_type == 'WEEKLY':
        return f"Semana del {inicio.strftime('%d/%m/%Y')} al {fin.strftime('%d/%m/%Y')}"
    if period_type == 'MONTHLY':
        return f"{nombres_mes[inicio.month - 1]} {inicio.year}"
    if period_type == 'QUARTERLY':
        return f"Trimestre {((inicio.month - 1) // 3) + 1} {inicio.year}"
    return str(inicio.year)


def _sumar_rango(location_ids, metric, period_type, desde, hasta,
                 usar_snapshots=True):
    """Totales del rango. Si el cajón (statistics_snapshots) tiene resúmenes
    para la métrica los suma; si está vacío (en la práctica nadie lo llena)
    lee de las tablas REALES: compras, consumo de cocina, mermas aprobadas y
    traslados valorizados. Las columnas que el cajón trae en 0 (snapshots
    viejos sin tasa EUR/Bs) se completan con la valoración real.

    Con `usar_snapshots=False` (rango desde/hasta explícito) se lee SIEMPRE de
    las tablas reales: un snapshot es el resumen de un período completo y
    sumarlo para un rango parcial mostraría montos fuera del intervalo."""
    metric = (metric or 'PURCHASES').upper()
    # El snapshot TRANSFERS guarda SOLO pérdidas (extravíos) para Egresos
    # operativos; no es el volumen logístico. Para el reporte se lee siempre
    # la mercancía realmente movida/recibida de las tablas operativas.
    if metric == 'TRANSFERS':
        return obtener_totales_reales(location_ids, metric, desde, hasta)
    if not usar_snapshots or not hay_snapshots_metrico(location_ids, metric,
                                                       period_type):
        return obtener_totales_reales(location_ids, metric, desde, hasta)

    totales = {
        'amount_usd': Decimal('0.00'),
        'amount_bs': Decimal('0.00'),
        'amount_eur': Decimal('0.00'),
        'quantity': Decimal('0.00'),
        'record_count': 0,
    }
    for loc_id in location_ids:
        parcial = obtener_snapshot_por_periodo(loc_id, metric, period_type,
                                               desde, hasta)
        for clave in ('amount_usd', 'amount_bs', 'amount_eur', 'quantity'):
            totales[clave] += parcial[clave]
        totales['record_count'] += parcial['record_count']

    # El cajón nunca se regenera: un snapshot guardado cuando todavía no había
    # tasa EUR (o cuando los bolívares se registraban como VES) trae 0 en esa
    # columna aunque el movimiento exista. Se completa SOLO la valoración en 0
    # con la de las tablas operativas; nunca se pisan montos ya calculados.
    if not any(totales[clave] for clave in
               ('amount_usd', 'amount_bs', 'amount_eur')):
        reales = obtener_totales_reales(location_ids, metric, desde, hasta)
        if any(reales[clave] for clave in
               ('amount_usd', 'amount_bs', 'amount_eur')):
            totales.update(reales)
    else:
        reales = None
        for clave in ('amount_usd', 'amount_bs', 'amount_eur'):
            if totales[clave]:
                continue
            if reales is None:
                reales = obtener_totales_reales(location_ids, metric,
                                                desde, hasta)
            totales[clave] = reales[clave]
        if not totales['record_count'] and reales is not None:
            totales['record_count'] = reales['record_count']

    for clave in ('amount_usd', 'amount_bs', 'amount_eur', 'quantity'):
        totales[clave] = _redondear(totales[clave])
    return totales


def _consolidado_por_periodo(location_ids, period_type, desde, hasta,
                             moneda='USD', incluir_compras=True):
    """Consolidado financiero del rango con datos REALES, convertido a la moneda
    seleccionada del reporte. El monto de la serie es la INVERSIÓN REAL en
    compras: los gastos de cocina, mermas y pérdidas de traslado son salidas de
    esa misma mercancía y sumarlos aquí duplicaría el egreso."""
    consolidado = consolidado_financiero(location_ids, desde, hasta, moneda,
                                          incluir_compras=incluir_compras)
    monto = consolidado['total_registrado']
    return {
        'amount_usd': monto,
        'amount_bs': monto,
        'amount_eur': monto,
        'quantity': Decimal('0.00'),
        'record_count': 0,
    }


def _operativo_por_sede(loc_id, inicio, fin, moneda='USD'):
    """Gasto operativo absorbido por una sede: cocina + mermas + pérdidas de
    traslado atribuidas a ella (la que despachó). Las compras NO se reparten:
    son centralizadas, así que el ranking compara solo costo operativo."""
    desde_dt = (inicio if isinstance(inicio, datetime)
                else datetime.combine(inicio, time.min))
    hasta_dt = (fin if isinstance(fin, datetime)
                else datetime.combine(fin, time.max))
    mermas = obtener_mermas_resumen([loc_id], desde_dt, hasta_dt)
    consumo = obtener_consumo_valorizado([loc_id], desde_dt, hasta_dt)
    direccional = obtener_traslados_direccional([loc_id], desde_dt, hasta_dt,
                                                moneda)

    def convertir(buckets):
        monto = _convertir_buckets(buckets, moneda, hasta_dt)
        return _redondear(monto) if monto is not None else Decimal('0.00')

    return _redondear(
        convertir(mermas['total']) + convertir(consumo['total'])
        + direccional['perdidas_por_sede'].get(loc_id, Decimal('0.00')))


def _ancla_inicial(location_ids, metric, period_type, referencia):
    if referencia is not None:
        return calcular_periodo(period_type, referencia)['period_start']
    disponibles = listar_periodos_disponibles(location_ids, metric, period_type)
    if disponibles:
        return disponibles[0]
    return calcular_periodo(period_type)['period_start']


def calcular_comparativo(actual, anterior, moneda='USD'):
    """Diferencia absoluta, % y dirección para las tres monedas del reporte."""
    resultado = {}
    moneda = (moneda or 'USD').upper()
    for divisa in MONEDAS:
        actual_m = actual.get(f'amount_{divisa.lower()}', Decimal('0'))
        anterior_m = anterior.get(f'amount_{divisa.lower()}', Decimal('0'))
        diferencia = _redondear(actual_m - anterior_m)
        pct = None
        if anterior_m != 0:
            pct = _redondear(((actual_m - anterior_m) / anterior_m) * 100)
        direccion = 'up' if diferencia > 0 else ('down' if diferencia < 0 else 'flat')
        resultado[divisa] = {
            'actual': _redondear(actual_m),
            'anterior': _redondear(anterior_m),
            'diferencia': diferencia,
            'pct': pct,
            'direccion': direccion,
        }
    resultado['base'] = moneda
    resultado['base_comparativo'] = resultado.get(moneda)
    return resultado


def _contrato_valorizacion():
    try:
        from app.inventory.services.product_cost_service import (
            obtener_costo_unitario,
            valorizar_cantidad,
        )
        return obtener_costo_unitario, valorizar_cantidad
    except ImportError:
        return None, None


@dataclass
class ReportFilters:
    location_id: int | None = None
    metric: str = 'PURCHASES'
    period_type: str = 'MONTHLY'
    period_start: date | None = None
    moneda: str = 'USD'
    desde: date | None = None
    hasta: date | None = None


def queda_reporte_usuario_autorizado(user_id, location_id=None):
    """Valida y devuelve (sede(s) efectivas, error). Si location_id es None se
    reporta la empresa completa dentro de las sedes permitidas del usuario."""
    permitidas = obtener_sedes_permitidas(user_id)
    if not permitidas:
        return [], 'El usuario no tiene sedes asignadas'
    if location_id is not None:
        if location_id not in permitidas:
            return [], 'Sede no permitida para este usuario'
        efectivas = [location_id]
    else:
        efectivas = permitidas
    return efectivas, None


def _limites_rango(desde, hasta, location_ids, metric):
    """Límites efectivos cuando se usa al menos un extremo del rango libre.

    Si solo llega `desde` (o solo `hasta`), el extremo faltante se completa con
    la primera/última fecha CON REGISTROS de la métrica. Antes un filtro de un
    solo lado se ignoraba por completo y el reporte volvía al mes cerrado.
    Devuelve (inicio, fin) o None si no hay ningún extremo."""
    if not (desde or hasta):
        return None
    if desde and hasta:
        return (desde, hasta) if desde <= hasta else (hasta, desde)
    fechas = fechas_con_registros(location_ids, metric)
    inicio = desde or (fechas[0] if fechas else (hasta or current_ve_time().date()))
    fin = hasta or (fechas[-1] if fechas else (desde or current_ve_time().date()))
    if fin < inicio:
        inicio, fin = fin, inicio
    return inicio, fin


def _marco_desde_filtros(filtros, location_ids, ref_metric):
    """Marco temporal del reporte. Con desde/hasta definidos usa el rango libre
    exacto (también si solo viene un extremo); sin ellos deriva el período del
    tipo seleccionado (ancla del cajón)."""
    limites = _limites_rango(filtros.desde, filtros.hasta, location_ids,
                             ref_metric)
    if limites:
        inicio, fin = limites
        duracion = (fin - inicio).days + 1
        previo_inicio = inicio - timedelta(days=duracion)
        previo_fin = inicio - timedelta(days=1)
        return {
            'period_type': filtros.period_type,
            'period_start': inicio,
            'period_end': fin,
            'previous_start': previo_inicio,
            'previous_end': previo_fin,
            'label': ('Del ' + inicio.strftime('%d/%m/%Y') + ' al '
                      + fin.strftime('%d/%m/%Y')),
            'previous_label': ('Del ' + previo_inicio.strftime('%d/%m/%Y')
                               + ' al ' + previo_fin.strftime('%d/%m/%Y')),
        }
    ancla = _ancla_inicial(location_ids, ref_metric, filtros.period_type,
                           filtros.period_start)
    inicio, fin = ancla, _fin_desde_inicio(filtros.period_type, ancla)
    previo_inicio = _inicio_anterior(filtros.period_type, ancla)
    previo_fin = inicio - timedelta(days=1)
    return {
        'period_type': filtros.period_type,
        'period_start': inicio,
        'period_end': fin,
        'previous_start': previo_inicio,
        'previous_end': previo_fin,
        'label': _etiqueta_periodo(filtros.period_type, inicio, fin),
        'previous_label': _etiqueta_periodo(filtros.period_type,
                                            previo_inicio, previo_fin),
    }


def construir_reporte(filtros, user_id):
    """Objeto de datos del reporte de una métrica: período, montos del cajón,
    comparativo con el período anterior y detalle sin valorizar."""
    efectivas, error = queda_reporte_usuario_autorizado(user_id,
                                                        filtros.location_id)
    if error:
        return {'error': error}

    metric = filtros.metric or 'PURCHASES'
    period_type = filtros.period_type or 'MONTHLY'
    moneda = filtros.moneda or 'USD'

    incluir_compras = aplica_compras(user_id, efectivas)
    if not incluir_compras and metric == 'PURCHASES':
        # Quien no gestiona la Central no ve compras; se mide por traslados.
        metric = 'TRANSFERS'

    marco = _marco_desde_filtros(filtros, efectivas, metric)
    inicio, fin = marco['period_start'], marco['period_end']
    previo_inicio, previo_fin = marco['previous_start'], marco['previous_end']

    # Con un rango libre (desde/hasta) el cajón de resúmenes no sirve: guarda
    # períodos completos. Se lee siempre de las tablas reales para no mostrar
    # acumulados fuera del intervalo elegido.
    usar_snapshots = not (filtros.desde or filtros.hasta)
    if metric == 'CONSOLIDATED':
        actual = _consolidado_por_periodo(efectivas, period_type, inicio, fin,
                                          moneda, incluir_compras=incluir_compras)
        anterior = _consolidado_por_periodo(efectivas, period_type,
                                            previo_inicio, previo_fin, moneda,
                                            incluir_compras=incluir_compras)
    else:
        actual = _sumar_rango(efectivas, metric, period_type, inicio, fin,
                              usar_snapshots=usar_snapshots)
        anterior = _sumar_rango(efectivas, metric, period_type,
                                previo_inicio, previo_fin,
                                usar_snapshots=usar_snapshots)
    comparativo = calcular_comparativo(actual, anterior, moneda)

    detalle = _detalle_metric(efectivas, metric, period_type,
                              datetime.combine(inicio, time.min),
                              datetime.combine(fin, time.max),
                              moneda,
                              incluir_compras=incluir_compras)
    # Monedas con monto que no se pudieron convertir por falta de tasa BCV: la
    # plantilla las avisa para que el total no se lea como si estuviera completo.
    monedas_sin_tasa = detalle.pop('monedas_sin_tasa', [])

    return {
        'filters': {
            'location_id': filtros.location_id,
            'location_ids': efectivas,
            'metric': metric,
            'period_type': period_type,
            'moneda': moneda,
        },
        # Rango efectivo del reporte: la ruta lo usa para que los gráficos
        # apliquen exactamente el mismo intervalo (también con un solo extremo).
        'range': {
            'desde': inicio,
            'hasta': fin,
            'explicito': bool(filtros.desde or filtros.hasta),
        },
        'period': {
            'start': inicio,
            'end': fin,
            'previous_start': previo_inicio,
            'previous_end': previo_fin,
            'label': marco['label'],
            'previous_label': marco['previous_label'],
        },
        'current': actual,
        'previous': anterior,
        'comparative': comparativo,
        'detail': detalle,
        'monedas_sin_tasa': monedas_sin_tasa,
    }


def _fin_desde_inicio(period_type, inicio):
    if period_type == 'WEEKLY':
        return inicio + timedelta(days=6)
    if period_type == 'QUARTERLY':
        return _add_months(inicio, 3) - timedelta(days=1)
    if period_type == 'ANNUAL':
        return _add_months(inicio, 12) - timedelta(days=1)
    return _add_months(inicio, 1) - timedelta(days=1)


def _inicio_anterior(period_type, inicio):
    if period_type == 'WEEKLY':
        return inicio - timedelta(days=7)
    if period_type == 'QUARTERLY':
        return _add_months(inicio, -3)
    if period_type == 'ANNUAL':
        return inicio.replace(year=inicio.year - 1)
    return _add_months(inicio, -1)


def _top_productos(por_producto, moneda, fecha, limite=5):
    """Ordena por producto el impacto monetario (convertido a la moneda del
    reporte con la tasa vigente al cierre del rango) y devuelve el principal
    junto al ranking corto. `por_producto` trae quantity + buckets por moneda.
    """
    filas = []
    for fila in por_producto or []:
        monto = _convertir_buckets(fila.get('buckets') or {}, moneda, fecha)
        filas.append({
            'product_id': fila.get('product_id'),
            'product_name': fila.get('product_name'),
            'quantity': _redondear(fila.get('quantity')),
            'monto': _redondear(monto or Decimal('0.00')),
        })
    filas.sort(key=lambda f: (-float(f['monto']), -float(f['quantity']),
                              f['product_name'] or ''))
    total = sum((f['monto'] for f in filas), Decimal('0.00'))
    for fila in filas:
        fila['pct'] = (_redondear((fila['monto'] / total) * 100)
                       if total else Decimal('0.00'))
    return {
        'moneda': moneda,
        'principal': filas[0] if filas else None,
        'filas': filas[:limite],
    }


def _detalle_metric(location_ids, metric, period_type, inicio, fin,
                    moneda='USD', incluir_compras=True):
    if metric == 'PURCHASES':
        filas = obtener_compras_por_proveedor(inicio, fin)
        buckets_filas = []
        for f in filas:
            buckets = {'USD': f.get('total_usd', Decimal('0.00')),
                       'BS': f.get('total_bs', Decimal('0.00')),
                       'EUR': f.get('total_eur', Decimal('0.00'))}
            buckets_filas.append(buckets)
            # Monto ya valorizado con la tasa del día de cada compra: antes se
            # reconvertía el Bs con la tasa de cierre (109,83 en vez de 109,95).
            f['monto'] = f['equivalente'].get(moneda, Decimal('0.00'))
            f['moneda'] = moneda
        return {'por_proveedor': filas,
                'monedas_sin_tasa': _monedas_sin_tasa(buckets_filas, moneda,
                                                      fin)}
    if metric == 'KITCHEN_CONSUMPTION':
        consumo = obtener_consumo_valorizado(location_ids, inicio, fin)
        return {'registros': obtener_resumen_consumo(location_ids, inicio, fin),
                'top_producto': _top_productos(consumo['por_producto'],
                                               moneda, fin),
                'por_sede': consumo['por_sede']}
    if metric == 'WASTE':
        registros = obtener_mermas_detalle(location_ids, inicio, fin)
        resumen_mermas = obtener_mermas_resumen(location_ids, inicio, fin)
        top_producto = _top_productos(
            obtener_mermas_top_producto(location_ids, inicio, fin),
            moneda, fin)
        buckets_filas = []
        for r in registros:
            r['cost_original'] = r['cost']
            r['origin_currency'] = r['currency']
            buckets_filas.append({_moneda_normalizada(r['origin_currency']):
                                  r['cost_original']})
            convertido = _convertir_monto(
                r['cost_original'], r['origin_currency'], moneda, fin)
            r['cost'] = _redondear(convertido) if convertido is not None else Decimal('0.00')
            r['currency'] = moneda
        return {'mermas': registros,
                'top_producto': top_producto,
                'por_sede': resumen_mermas['por_sede'],
                'monedas_sin_tasa': _monedas_sin_tasa(buckets_filas, moneda,
                                                      fin)}
    if metric == 'TRANSFERS':
        orientacion = _orientacion_efectiva(location_ids, incluir_compras)
        resumen = obtener_resumen_traslados(location_ids, inicio, fin,
                                            orientacion)
        direccional = obtener_traslados_direccional(location_ids, inicio, fin,
                                                    moneda, orientacion)
        datos = obtener_traslados_valorizados(location_ids, inicio, fin,
                                              orientacion)
        perdidas = (_convertir_buckets(datos['perdidas'], 'USD', fin)
                    or Decimal('0.00'))
        convertido = _convertir_monto(perdidas, 'USD', moneda, fin)
        resumen['perdidas_valorizadas'] = (
            _redondear(convertido) if convertido is not None else Decimal('0.00'))
        resumen['extravios_valorizados'] = True
        resumen['direccional'] = direccional
        resumen['movimientos'] = direccional['movimientos']
        resumen['perdidas_detalle'] = direccional['perdidas_detalle']
        resumen['perdidas_conteo'] = direccional['perdidas_conteo']
        # La cantidad de extravíos debe salir de la MISMA fuente que la tabla de
        # detalle (misma exclusión de devoluciones/anulados y de pérdidas en
        # tránsito). Antes el resumen contaba también devoluciones y arrojaba
        # una cifra mayor que la suma de las líneas mostradas.
        resumen['extravios_quantity'] = direccional['extravios_quantity']
        recibido = obtener_recibido_por_insumo(location_ids, inicio, fin)
        resumen['recibido_por_insumo'] = recibido
        if SEDE_CENTRAL_ID not in location_ids:
            # Regla de negocio: las sedes no centrales no envían, solo reciben
            # y, si acaso, devuelven mercancía a la Central. Lo que sale de
            # ellas se etiqueta 'devueltos' (idem en el flujo direccional).
            resumen['tiene_enviados'] = False
            resumen['devueltos'] = resumen['enviados']
            resumen['enviados'] = 0
            direccional['devueltos'] = direccional.pop('enviados',
                                                       _cubo_direccion_vacio())
            for mv in resumen['movimientos']:
                if mv['direccion'] == 'enviados':
                    mv['direccion'] = 'devueltos'
        else:
            resumen['tiene_enviados'] = True
        if len(location_ids) > 1:
            # Ámbito multi-sede: 'recibidos' se mide por sede de DESTINO, no
            # por la orientación de la Central. Un despacho Central → sucursal
            # salió de la Central (enviado) pero también llegó a una sede
            # visible (recibido), igual que 'Mercancía recibida'. Se valoriza
            # con la cantidad realmente recepcionada, no la despachada.
            recibidos = {'conteo': 0, 'quantity': Decimal('0.00'),
                         'buckets': _bucket_vacio()}
            for fila in datos['filas']:
                if fila.get('destination_id') not in location_ids:
                    continue
                if not fila.get('received_quantity'):
                    continue
                recibidos['conteo'] += 1
                recibidos['quantity'] += fila['received_quantity']
                for m in MONEDAS:
                    recibidos['buckets'][m] += fila['buckets_recibido'].get(
                        m, Decimal('0.00'))
            costo_recibido = _convertir_buckets(recibidos['buckets'], moneda,
                                                fin)
            direccional['recibidos'] = {
                'conteo': recibidos['conteo'],
                'quantity': _redondear(recibidos['quantity']),
                'cost': (_redondear(costo_recibido)
                         if costo_recibido is not None else Decimal('0.00')),
            }
            resumen['recibidos'] = recibidos['conteo']
        # La fila Total se recalcula con las direcciones que la tabla muestra
        # (sin los internos que ya se plegaron a recibidos).
        claves_total = (['devueltos', 'recibidos']
                        if not resumen['tiene_enviados']
                        else ['recibidos', 'enviados'])
        direccional['total'] = {
            'conteo': sum(direccional[k]['conteo'] for k in claves_total),
            'quantity': _redondear(sum((direccional[k]['quantity']
                                        for k in claves_total),
                                       Decimal('0.00'))),
            'cost': _redondear(sum((direccional[k]['cost']
                                    for k in claves_total),
                                   Decimal('0.00'))),
        }
        # Aviso de tasas faltantes: los costos son parciales si alguna moneda
        # con monto en el período no tiene tasa BCV para convertirse.
        buckets_reportados = [f['buckets'] for f in datos['filas']]
        buckets_reportados.extend(f['buckets_recibido']
                                  for f in datos['filas'])
        buckets_reportados.append(datos['perdidas'])
        resumen['monedas_sin_tasa'] = _monedas_sin_tasa(buckets_reportados,
                                                        moneda, fin)
        return resumen
    if metric == 'CONSOLIDATED':
        consolidado = consolidado_financiero(location_ids, inicio, fin, moneda,
                                             incluir_compras=incluir_compras)
        # La vista consolidada también reporta pérdidas de traslado, así que
        # debe llevar el MISMO detalle por producto/lote que la vista de
        # traslados. Antes solo se empaquetaba en TRANSFERS y la tabla nunca
        # se pintaba en el reporte consolidado.
        orientacion = _orientacion_efectiva(location_ids, incluir_compras)
        direccional = obtener_traslados_direccional(location_ids, inicio, fin,
                                                    moneda, orientacion)
        return {'consolidado': consolidado,
                'moneda': moneda,
                'perdidas_valorizadas': direccional['perdidas'],
                'perdidas_detalle': direccional['perdidas_detalle'],
                'perdidas_conteo': direccional['perdidas_conteo'],
                'extravios_quantity': direccional['extravios_quantity'],
                'monedas_sin_tasa': _monedas_sin_tasa(
                    [f['buckets'] for f in consolidado['por_concepto']],
                    moneda, fin)}
    return {}


def _cubo_direccion_vacio():
    return {'conteo': 0, 'quantity': Decimal('0.00'),
            'buckets': _bucket_vacio(), 'cost': Decimal('0.00')}


def _agrupar_direccional(filas, moneda, fecha):
    """Agrupa las filas de obtener_traslados_valorizados por dirección y
    convierte el costo a la moneda del reporte con la tasa vigente en 'fecha'.
    Las filas con cuenta_direccion=False (p. ej. un traslado en tránsito que
    todavía no llegó) se omiten: no suman a recibidos ni internos."""
    base = {d: {'conteo': 0, 'quantity': Decimal('0.00'),
                'buckets': _bucket_vacio()}
            for d in ('enviados', 'recibidos', 'internos')}
    for fila in filas:
        if not fila.get('cuenta_direccion', True):
            continue
        ag = base[fila['direccion']]
        ag['conteo'] += 1
        ag['quantity'] += fila['quantity']
        for m in MONEDAS:
            ag['buckets'][m] += fila['buckets'].get(m, Decimal('0.00'))

    resultado = {}
    for d, ag in base.items():
        monto = _convertir_buckets(ag['buckets'], moneda, fecha)
        resultado[d] = {
            'conteo': ag['conteo'],
            'quantity': _redondear(ag['quantity']),
            'cost': (_redondear(monto) if monto is not None
                     else Decimal('0.00')),
        }
    return resultado


def obtener_traslados_direccional(location_ids, desde, hasta, moneda='USD',
                                  orientacion_id=None):
    """Resumen direccional REAL de los movimientos del rango con su mercancía
    y costo (último costo de compra por producto/lote), convertido a la moneda
    elegida: recibidos (entraron a tus sedes), enviados (salieron de ellas) e
    internos. Cada dirección trae conteo (nº de traslados), quantity (enviados:
    lo despachado; recibidos e internos: lo realmente llegado) y cost (valor
    convertido). Además trae total_despachado (lo que salió físicamente, sin
    importar la dirección) para los KPIs que miden mercancía movida. Con
    orientacion_id (la Central para quien la gestiona) la dirección se narra
    desde esa sede."""
    moneda = (moneda or 'USD').upper()
    if isinstance(desde, datetime):
        desde_dt = desde
    else:
        desde_dt = datetime.combine(desde, time.min)
    if isinstance(hasta, datetime):
        hasta_dt = hasta
    else:
        hasta_dt = datetime.combine(hasta, time.max)

    datos = obtener_traslados_valorizados(location_ids, desde_dt, hasta_dt,
                                          orientacion_id)
    direccional = _agrupar_direccional(datos['filas'], moneda, hasta_dt)
    total = {'conteo': 0, 'quantity': Decimal('0.00'), 'cost': Decimal('0.00')}
    for d in ('enviados', 'recibidos', 'internos'):
        total['conteo'] += direccional[d]['conteo']
        total['quantity'] += direccional[d]['quantity']
        total['cost'] += direccional[d]['cost']

    def convertir(buckets):
        monto = _convertir_buckets(buckets, moneda, hasta_dt)
        return _redondear(monto) if monto is not None else Decimal('0.00')

    # Total despachado (independiente de la dirección): lo usa el dashboard del
    # Admin para seguir midiendo "uds. movidas" como lo que salió físicamente.
    buckets_despachado = _bucket_vacio()
    cantidad_despachada = Decimal('0.00')
    for f in datos['filas']:
        cantidad_despachada += f['despachado']
        for m in MONEDAS:
            buckets_despachado[m] += f['buckets_despachado'].get(
                m, Decimal('0.00'))
    total_despachado = {
        'conteo': len(datos['filas']),
        'quantity': _redondear(cantidad_despachada),
        'cost': convertir(buckets_despachado),
    }

    movimientos = [{
        'id': f['id'],
        'date': f['date'],
        'type': f['type'],
        'status': f['status'],
        'direccion': f['direccion'],
        'origin_name': f['origin_name'],
        'destination_name': f['destination_name'],
        'quantity': f['quantity'],
        'cost': convertir(f['buckets']),
    } for f in datos['filas']]

    perdidas = (_convertir_buckets(datos['perdidas'], moneda, hasta_dt)
                or Decimal('0.00'))

    # Detalle de los traslados PERDIDOS: qué producto y cuánta cantidad no
    # llegó, con su valorización en la moneda del reporte. El conteo cuenta
    # traslados distintos (un traslado puede perder varios productos).
    perdidas_detalle = [{
        'movement_id': fila['movement_id'],
        'date': fila['date'],
        'type': fila['type'],
        'status': fila['status'],
        'origin_name': fila['origin_name'],
        'destination_name': fila['destination_name'],
        'product_id': fila['product_id'],
        'product_name': fila['product_name'],
        'lot_number': fila['lot_number'],
        'quantity': fila['quantity'],
        'cost': convertir(fila['buckets']),
    } for fila in datos.get('perdidas_detalle', [])]
    perdidas_conteo = len({fila['movement_id'] for fila in perdidas_detalle})

    # Pérdidas (extravíos) atribuidas a la sede que DESPACHÓ: es la que asumió
    # el costo de la mercancía que salió y no llegó completa.
    perdidas_por_sede = {}
    for f in datos['filas']:
        if not any(f['perdidas'].values()):
            continue
        monto_sede = (_convertir_buckets(f['perdidas'], moneda, hasta_dt)
                      or Decimal('0.00'))
        perdidas_por_sede[f['origin_id']] = _redondear(
            perdidas_por_sede.get(f['origin_id'], Decimal('0.00'))
            + monto_sede)

    # Totales de lo REALMENTE RECIBIDO por las sedes de destino visibles. Es
    # la misma base que alimenta 'recibido_por_sede', así que las tarjetas de
    # control logístico y la tabla por sede coinciden al céntimo. Lo que aún
    # está en camino no se suma aquí: se informa aparte como 'en_transito'.
    ids = set(location_ids or [])
    recibido_total = {'conteo': 0, 'quantity': Decimal('0.00'),
                      'buckets': _bucket_vacio()}
    en_transito = {'conteo': 0, 'quantity': Decimal('0.00'),
                   'buckets': _bucket_vacio()}
    sin_recepcion = {'conteo': 0, 'quantity': Decimal('0.00'),
                     'buckets': _bucket_vacio()}
    for f in datos['filas']:
        destino = f['destination_id']
        if destino not in ids or destino == SEDE_CENTRAL_ID:
            continue
        if f['received_quantity'] > 0:
            ag, cantidad, buckets = (recibido_total,
                                     f['received_quantity'],
                                     f['buckets_recibido'])
        else:
            ag = (en_transito
                  if f['status'] in ESTADOS_TRASLADO_EN_TRANSITO
                  else sin_recepcion)
            cantidad = f['despachado']
            buckets = f['buckets_despachado']
        ag['conteo'] += 1
        ag['quantity'] += cantidad
        for m in MONEDAS:
            ag['buckets'][m] += buckets.get(m, Decimal('0.00'))

    def _resumen_flujo(ag):
        return {'conteo': ag['conteo'],
                'quantity': _redondear(ag['quantity']),
                'cost': convertir(ag['buckets'])}

    recibido_total = _resumen_flujo(recibido_total)
    en_transito = _resumen_flujo(en_transito)
    sin_recepcion = _resumen_flujo(sin_recepcion)

    # Mercancía realmente recibida por cada sede de destino (sin la Central,
    # que no es una sucursal receptora). Solo traslados consolidados.
    recibido_por_sede = {}
    for f in datos['filas']:
        destino = f['destination_id']
        if destino not in ids or destino == SEDE_CENTRAL_ID:
            continue
        if not f['received_quantity']:
            continue
        ag = recibido_por_sede.setdefault(destino, {
            'sede': f['destination_name'], 'conteo': 0,
            'quantity': Decimal('0.00'), 'buckets': _bucket_vacio()})
        ag['conteo'] += 1
        ag['quantity'] += f['received_quantity']
        for m in MONEDAS:
            ag['buckets'][m] += f['buckets_recibido'].get(m, Decimal('0.00'))
    recibido = []
    for ag in recibido_por_sede.values():
        recibido.append({
            'sede': ag['sede'], 'conteo': ag['conteo'],
            'quantity': _redondear(ag['quantity']),
            'monto': convertir(ag['buckets']),
        })
    recibido.sort(key=lambda r: -float(r['monto']))

    return {
        'moneda': moneda,
        'enviados': direccional['enviados'],
        'recibidos': direccional['recibidos'],
        'internos': direccional['internos'],
        'total': total,
        'total_despachado': total_despachado,
        'movimientos': movimientos,
        'perdidas': _redondear(perdidas),
        'perdidas_detalle': perdidas_detalle,
        'perdidas_conteo': perdidas_conteo,
        'perdidas_por_sede': perdidas_por_sede,
        'recibido_total': recibido_total,
        'en_transito': en_transito,
        'sin_recepcion': sin_recepcion,
        'recibido_por_sede': recibido,
        'extravios_quantity': datos['extravios_quantity'],
    }


def consolidado_financiero(location_ids, desde, hasta, moneda='USD',
                           incluir_compras=True):
    """Gasto REAL del rango convertido a la moneda seleccionada del reporte
    (por defecto USD). Presenta cada rubro por separado y sin restas
    residuales:
      - por_concepto: Compras (solo moneda nativa de pago), Gastos de cocina y
        Mermas y pérdidas de traslado, todos en magnitud positiva.
      - por_sede: gasto OPERATIVO absorbido por cada sede (cocina + mermas +
        pérdidas de traslado). Excluye compras: son centralizadas.
      - traslados.recibido_por_sede / traslados.devoluciones: mercancía que
        llegó a cada sede por traslados consolidados y devoluciones a la
        Central (los retornos no cuentan como traslados).
      - total_operativo: Gastos de cocina + Mermas y pérdidas de traslado.
      - total_registrado: INVERSIÓN REAL en compras. Cocina y pérdidas no se
        suman: son porciones de la misma mercancía ya comprada (doble conteo).
      - distribucion: destino de la mercancía comprada en % (disponible,
        cocina, mermas y pérdidas de traslado).
      - traslados: control logístico de lo REALMENTE RECIBIDO por las sedes de
        destino (conteo, cantidad y costo a valor de inventario), de modo que
        las tarjetas coinciden con la tabla por sede. Lo que sigue en camino
        viaja aparte en 'en_transito' y no suma; sus pérdidas sí se agrupan con
        las mermas.
    Las compras se valoran con la tasa del día de cada compra (el BS registrado
    en price_bs); consumo/mermas con la última tasa BCV del período. Si
    incluir_compras es False (sedes que no gestionan la Central) las compras se
    omiten por completo."""
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    if isinstance(desde, datetime):
        desde_dt = desde
    else:
        desde_dt = datetime.combine(desde, time.min)
    if isinstance(hasta, datetime):
        hasta_dt = hasta
    else:
        hasta_dt = datetime.combine(hasta, time.max)

    def convertir(buckets):
        total = _convertir_buckets(buckets, moneda, hasta_dt)
        return _redondear(total) if total is not None else Decimal('0.00')

    compras = (obtener_compras_consolidado(desde_dt, hasta_dt)
               if incluir_compras else [])
    mermas = obtener_mermas_resumen(location_ids, desde_dt, hasta_dt)
    consumo = obtener_consumo_valorizado(location_ids, desde_dt, hasta_dt)

    compras_totales = _bucket_vacio()
    for linea in compras:
        for m in MONEDAS:
            compras_totales[m] += linea['buckets'].get(m, Decimal('0.00'))
    compras_totales = {m: _redondear(v) for m, v in compras_totales.items()}

    por_categoria = {}
    for linea in compras:
        cat = linea['category']
        por_categoria.setdefault(cat, _bucket_vacio())
        for m in MONEDAS:
            # Equivalente valorizado con la tasa del día de cada compra: así la
            # suma de las categorías coincide al céntimo con 'Compras' y no se
            # reconvierte el Bs registrado con la tasa de cierre.
            por_categoria[cat][m] += linea['equivalente'].get(
                m, Decimal('0.00'))
    compras_monto = (_compras_en_moneda(desde_dt, hasta_dt, moneda)
                     if incluir_compras else Decimal('0.00'))

    total_consumo = convertir(consumo['total'])
    total_mermas = convertir(mermas['total'])

    # Traslados: se mide la mercancía despachada (volumen) y su valorización a
    # costo. Las PÉRDIDAS de traslado (extravíos) ya no quedan fuera del
    # análisis: se agrupan con las mermas como pérdida operativa de mercancía.
    direccional = obtener_traslados_direccional(
        location_ids, desde_dt, hasta_dt, moneda,
        orientacion_id=_orientacion_efectiva(location_ids, incluir_compras))
    # Las tarjetas miden lo RECIBIDO (misma base que la tabla por sede); lo
    # despachado y aún en camino se informa aparte, sin sumarse al costo.
    recibido = direccional['recibido_total']
    total_perdidas_traslado = _redondear(direccional['perdidas'])
    # Devoluciones al Almacén Central: no cuentan como traslados de
    # abastecimiento, pero sí se informan con su monto (mercancía devuelta).
    devoluciones_datos = obtener_devoluciones_central(location_ids, desde_dt,
                                                      hasta_dt)
    devoluciones_por_sede = [
        {'sede': sede,
         'conteo': ag['conteo'],
         'quantity': _redondear(ag['quantity']),
         'monto': convertir(ag['buckets'])}
        for sede, ag in devoluciones_datos['por_sede'].items()
    ]
    devoluciones_por_sede.sort(key=lambda f: -float(f['monto']))
    traslados = {
        'moneda': moneda,
        'conteo': recibido['conteo'],
        'quantity': _redondear(recibido['quantity']),
        'costo': _redondear(recibido['cost']),
        'en_transito': direccional['en_transito'],
        'sin_recepcion': direccional['sin_recepcion'],
        'recibido_por_sede': direccional['recibido_por_sede'],
        'devoluciones': {
            'conteo': devoluciones_datos['conteo'],
            'quantity': _redondear(devoluciones_datos['quantity']),
            'monto': convertir(devoluciones_datos['buckets']),
            'por_sede': devoluciones_por_sede,
        },
    }

    total_mermas_perdidas = _redondear(total_mermas + total_perdidas_traslado)
    total_operativo = _redondear(total_consumo + total_mermas_perdidas)
    # La inversión REAL es la compra a proveedores. Cocina, mermas y pérdidas
    # salen de esa misma mercancía: sumarlas sería doble conteo (231,85 → 209,95).
    total_registrado = (compras_monto if incluir_compras else total_operativo)

    buckets_mermas_perdidas = {
        m: _redondear(mermas['total'].get(m, Decimal('0.00')))
        for m in MONEDAS}
    # Las pérdidas de traslado ya vienen convertidas a la moneda del reporte.
    buckets_mermas_perdidas[moneda] = _redondear(
        buckets_mermas_perdidas[moneda] + total_perdidas_traslado)

    por_concepto = []
    if incluir_compras:
        por_concepto.append({'concepto': 'Compras', 'tipo': 'abastecimiento',
                             'monto': compras_monto,
                             'buckets': compras_totales})
    por_concepto.extend([
        {'concepto': 'Gastos de cocina', 'tipo': 'operativo',
         'monto': total_consumo,
         'buckets': {m: _redondear(consumo['total'].get(m, Decimal('0.00')))
                     for m in MONEDAS}},
        {'concepto': 'Mermas y pérdidas de traslado', 'tipo': 'operativo',
         'monto': total_mermas_perdidas,
         'buckets': buckets_mermas_perdidas,
         'mermas': total_mermas,
         'perdidas_traslado': total_perdidas_traslado},
    ])

    # Dona "Distribución del período": en qué se fue la mercancía COMPRADA,
    # expresada en porcentaje. No repite la evolución lineal (montos por mes).
    distribucion = []
    if incluir_compras and compras_monto > 0:
        componentes = total_consumo + total_mermas + total_perdidas_traslado
        base = (compras_monto if compras_monto >= componentes
                else componentes)
        disponible = _redondear(
            max(compras_monto - componentes, Decimal('0.00')))

        def pct(parte):
            return _redondear((parte / base) * 100) if base else Decimal('0.00')

        distribucion = [
            {'clave': 'disponible', 'label': 'Disponible / comercializado',
             'monto': disponible, 'pct': pct(disponible)},
            {'clave': 'cocina', 'label': 'Consumo de cocina',
             'monto': total_consumo, 'pct': pct(total_consumo)},
            {'clave': 'mermas', 'label': 'Mermas',
             'monto': total_mermas, 'pct': pct(total_mermas)},
            {'clave': 'perdidas_traslado', 'label': 'Pérdidas de traslado',
             'monto': total_perdidas_traslado,
             'pct': pct(total_perdidas_traslado)},
        ]
        distribucion = [f for f in distribucion if f['monto'] > 0]
        if distribucion:
            # Cierre contable: el redondeo a 2 decimales debe sumar 100,00 %.
            mayor = max(distribucion, key=lambda f: f['pct'])
            sobrante = Decimal('100.00') - sum(f['pct'] for f in distribucion)
            mayor['pct'] = _redondear(mayor['pct'] + sobrante)

    por_categoria_filas = [
        {'category': cat, 'monto': _redondear(b.get(moneda, Decimal('0.00')))}
        for cat, b in por_categoria.items()
    ]
    por_categoria_filas.sort(key=lambda f: -float(f['monto']))

    # "Por sede" es ESTRICTAMENTE gasto operativo absorbido por cada sede:
    # cocina + mermas + pérdidas de traslado. Las compras son centralizadas y
    # no se reparten entre sucursales (antes se sumaba "Compras Central").
    nombres_sedes = obtener_nombres_sedes(location_ids)
    por_sede_map = {}

    def _fila_sede(nombre):
        return por_sede_map.setdefault(nombre, {
            'sede': nombre, 'mermas': Decimal('0.00'),
            'cocina': Decimal('0.00'), 'perdidas': Decimal('0.00')})

    for sede, valores in mermas['por_sede'].items():
        _fila_sede(sede)['mermas'] += convertir(valores)
    for sede, valores in consumo['por_sede'].items():
        _fila_sede(sede)['cocina'] += convertir(valores)
    for loc_id, monto in direccional['perdidas_por_sede'].items():
        _fila_sede(nombres_sedes.get(loc_id, f'Sede #{loc_id}'))['perdidas'] += monto

    por_sede = []
    for fila in por_sede_map.values():
        fila['monto'] = _redondear(fila['mermas'] + fila['cocina']
                                   + fila['perdidas'])
        fila['mermas'] = _redondear(fila['mermas'])
        fila['cocina'] = _redondear(fila['cocina'])
        fila['perdidas'] = _redondear(fila['perdidas'])
        if fila['monto'] > 0:
            por_sede.append(fila)
    por_sede.sort(key=lambda f: -float(f['monto']))

    return {
        'moneda': moneda,
        'por_concepto': por_concepto,
        'por_categoria': por_categoria_filas,
        'por_sede': por_sede,
        'por_moneda': (_por_moneda_panel(desde_dt, hasta_dt, moneda)
                       if incluir_compras else {'moneda': moneda,
                                                'filas': [],
                                                'total': Decimal('0.00')}),
        'total_compras': _redondear(compras_monto),
        'total_operativo': total_operativo,
        'total_registrado': total_registrado,
        'total_etiqueta': ('Inversión real en compras' if incluir_compras
                           else 'Pérdidas operativas del período'),
        'mermas': total_mermas,
        'perdidas_traslado': total_perdidas_traslado,
        'distribucion': distribucion,
        'traslados': traslados,
    }


def _total_moneda(totales, moneda, fecha):
    """Convierte a la moneda del reporte un total con buckets DISJUNTOS (cada
    registro valorizado en una sola moneda: traslados, mermas, consumo). Los
    snapshots no pasan por aquí: ya traen la valoración en las tres monedas."""
    total = Decimal('0.00')
    for origen in MONEDAS:
        monto = totales.get(f'amount_{origen.lower()}', Decimal('0.00'))
        monto = monto or Decimal('0.00')
        if not monto:
            continue
        convertido = _convertir_monto(monto, origen, moneda, fecha)
        if convertido is not None:
            total += convertido
    return _redondear(total)


def _valor_con_respaldo(location_ids, metric, period_type, inicio, fin,
                        moneda, totales):
    """Valor del rango en la moneda pedida, con respaldo a las tablas reales.

    Si el cajón trae 0 en la columna de esa moneda (snapshots viejos sin tasa
    EUR o con los bolívares como VES) se recalcula al vuelo desde las tablas
    operativas, para que el KPI, el ranking y la gráfica de evolución no se
    contradigan mostrando ceros donde sí hubo gasto.
    """
    moneda = _moneda_normalizada(moneda)
    valor = (totales.get(f'amount_{moneda.lower()}', Decimal('0.00'))
             or Decimal('0.00'))
    if valor:
        return valor
    desde_dt = (inicio if isinstance(inicio, datetime)
                else datetime.combine(inicio, time.min))
    hasta_dt = (fin if isinstance(fin, datetime)
                else datetime.combine(fin, time.max))
    if metric == 'PURCHASES':
        # Compra por compra con la tasa del día que quedó registrada.
        return _compras_en_moneda(desde_dt, hasta_dt, moneda)
    reales = obtener_totales_reales(location_ids, metric, desde_dt, hasta_dt)
    if not reales.get('record_count') and not any(
            reales[clave] for clave in
            ('amount_usd', 'amount_bs', 'amount_eur')):
        return valor
    return _total_moneda(reales, moneda, hasta_dt)


def obtener_metrica_por_sede(location_ids, metric, period_type, inicio, fin,
                             moneda='USD', incluir_compras=True,
                             usar_snapshots=True):
    """Un renglón por sede para el ranking y la comparativa lateral.

    ``total_base`` se expresa en la moneda del reporte: los montos reales
    guardados en su moneda original se convierten con la tasa vigente al cierre
    del período. Las compras se convierten compra por compra (con la tasa
    registrada en cada una) para no mezclar las valoraciones paralelas USD/Bs
    del mismo gasto. Si la sede lee snapshots, se elige la moneda ya calculada.
    """
    metric = (metric or 'PURCHASES').upper()
    moneda = (moneda or 'USD').upper()
    nombres = obtener_nombres_sedes(location_ids)
    renglones = []
    desde_dt = (inicio if isinstance(inicio, datetime)
                else datetime.combine(inicio, time.min))
    hasta_dt = (fin if isinstance(fin, datetime)
                else datetime.combine(fin, time.max))
    compras_base = None
    for loc_id in location_ids:
        if metric == 'CONSOLIDATED':
            # Ranking consolidado = gasto operativo por sede, sin compras
            # (las compras son una sola inversión central, no de la sede).
            total_sede = _operativo_por_sede(loc_id, inicio, fin, moneda)
            totales = {'amount_usd': total_sede, 'amount_bs': total_sede,
                       'amount_eur': total_sede, 'quantity': Decimal('0.00'),
                       'record_count': 0}
        else:
            totales = _sumar_rango([loc_id], metric, period_type,
                                   inicio, fin,
                                   usar_snapshots=usar_snapshots)
        if metric == 'CONSOLIDATED':
            # El consolidado ya viene expresado en la moneda del reporte.
            total_base = totales['amount_usd']
        elif metric == 'TRANSFERS':
            # Flujo homogéneo por sede: mercancía RECIBIDA en cada destino.
            # La Central no acumula aquí las pérdidas del snapshot.
            recibido = obtener_traslados_direccional(
                [loc_id], desde_dt, hasta_dt, moneda)['recibidos']
            total_base = _redondear(recibido['cost'])
            totales = {'amount_usd': Decimal('0.00'),
                       'amount_bs': Decimal('0.00'),
                       'amount_eur': Decimal('0.00'),
                       'quantity': recibido['quantity'],
                       'record_count': recibido['conteo']}
            totales[f'amount_{moneda.lower()}'] = total_base
        elif usar_snapshots and hay_snapshots_metrico([loc_id], metric,
                                                       period_type):
            # Los snapshots traen las tres valoraciones: se elige la pedida y,
            # si quedó en 0, se recalcula desde las tablas reales.
            total_base = _valor_con_respaldo(
                [loc_id], metric, period_type, inicio, fin, moneda, totales)
        elif metric == 'PURCHASES' and moneda == 'BS':
            # El BS registrado (price_bs) es el valor exacto del día de compra.
            # Las compras son de la Central: una sucursal sin snapshot propio
            # no hereda el total global.
            total_base = (totales.get('amount_bs', Decimal('0.00'))
                          if loc_id == SEDE_CENTRAL_ID else Decimal('0.00'))
        elif metric == 'PURCHASES':
            if loc_id == SEDE_CENTRAL_ID:
                if compras_base is None:
                    compras_base = _compras_en_moneda(desde_dt, hasta_dt, moneda)
                total_base = compras_base
            else:
                # La sucursal no tiene compras propias: 0, nunca el global.
                total_base = Decimal('0.00')
        else:
            total_base = _total_moneda(totales, moneda, hasta_dt)
        # Compras: una sucursal sin snapshot propio no debe exponer el total
        # global en amount_usd/amount_bs/amount_eur del renglón.
        if (metric == 'PURCHASES' and loc_id != SEDE_CENTRAL_ID
                and not (usar_snapshots and hay_snapshots_metrico(
                    [loc_id], metric, period_type))):
            totales = {'amount_usd': Decimal('0.00'),
                       'amount_bs': Decimal('0.00'),
                       'amount_eur': Decimal('0.00'),
                       'quantity': Decimal('0.00'),
                       'record_count': 0}
        nombre_sede = nombres.get(loc_id) or f'Sede #{loc_id}'
        renglones.append({
            'location_id': loc_id,
            'location_name': nombre_sede,
            'amount_usd': _redondear(totales['amount_usd']),
            'amount_bs': _redondear(totales['amount_bs']),
            'amount_eur': _redondear(totales['amount_eur']),
            'quantity': _redondear(totales['quantity']),
            'record_count': totales['record_count'],
            'moneda': moneda,
            'total_base': _redondear(total_base),
        })
    return renglones


def obtener_ranking(location_ids, metric, period_start=None, period_type='MONTHLY',
                    moneda='USD', incluir_compras=True, desde=None, hasta=None):
    """Ranking de sedes para una métrica, ordenado por monto en la moneda base
    (mayor primero) con su comparativa contra el período anterior."""
    metric = (metric or 'PURCHASES').upper()
    limites = _limites_rango(desde, hasta, location_ids, metric)
    if limites:
        inicio, fin = limites
        duracion = (fin - inicio).days + 1
        previo_inicio, previo_fin = (inicio - timedelta(days=duracion),
                                     inicio - timedelta(days=1))
    else:
        ancla = _ancla_inicial(location_ids, metric, period_type, period_start)
        inicio, fin = ancla, _fin_desde_inicio(period_type.upper(), ancla)
        marco = calcular_periodo(period_type.upper(), ancla)
        previo_inicio, previo_fin = (marco['previous_start'],
                                     marco['previous_end'])

    moneda = (moneda or 'USD').upper()
    usar_snapshots = limites is None
    renglones = obtener_metrica_por_sede(location_ids, metric, period_type.upper(),
                                         inicio, fin, moneda,
                                         incluir_compras=incluir_compras,
                                         usar_snapshots=usar_snapshots)
    previo_desde = (previo_inicio if isinstance(previo_inicio, datetime)
                    else datetime.combine(previo_inicio, time.min))
    previo_hasta = (previo_fin if isinstance(previo_fin, datetime)
                    else datetime.combine(previo_fin, time.max))
    for renglon in renglones:
        loc_id = renglon['location_id']
        if metric == 'CONSOLIDATED':
            anterior_m = _operativo_por_sede(loc_id, previo_inicio,
                                             previo_fin, moneda)
        else:
            previo = _sumar_rango([loc_id], metric,
                                  period_type.upper(), previo_inicio,
                                  previo_fin,
                                  usar_snapshots=usar_snapshots)
            if metric == 'TRANSFERS':
                anterior_m = obtener_traslados_direccional(
                    [loc_id], previo_desde, previo_hasta, moneda
                )['recibidos']['cost']
            elif usar_snapshots and hay_snapshots_metrico([loc_id], metric,
                                                        period_type):
                anterior_m = _valor_con_respaldo(
                    [loc_id], metric, period_type.upper(), previo_inicio,
                    previo_fin, moneda, previo)
            elif metric == 'PURCHASES' and moneda == 'BS':
                anterior_m = (previo.get('amount_bs', Decimal('0.00'))
                              if loc_id == SEDE_CENTRAL_ID
                              else Decimal('0.00'))
            elif metric == 'PURCHASES':
                anterior_m = (_compras_en_moneda(previo_desde, previo_hasta,
                                                 moneda)
                              if loc_id == SEDE_CENTRAL_ID
                              else Decimal('0.00'))
            else:
                anterior_m = _total_moneda(previo, moneda, previo_hasta)
        actual_m = renglon['total_base']
        renglon['anterior'] = _redondear(anterior_m)
        renglon['diferencia'] = _redondear(actual_m - anterior_m)
        renglon['pct'] = (_redondear(((actual_m - anterior_m) / anterior_m) * 100)
                          if anterior_m != 0 else None)

    renglones.sort(key=lambda r: -float(r['total_base']))
    return renglones


def _segmentos_rango(desde, hasta):
    """Divide un rango libre en puntos de gráfico SIN salirse de él: un punto
    por día hasta 31 días; si es mayor, un único punto con el total del rango.
    Devuelve [(inicio, fin, etiqueta)]."""
    dias = (hasta - desde).days + 1
    if dias <= 31:
        return [(desde + timedelta(days=i), desde + timedelta(days=i),
                 (desde + timedelta(days=i)).strftime('%d/%m/%Y'))
                for i in range(dias)]
    return [(desde, hasta,
             'Del ' + desde.strftime('%d/%m/%Y') + ' al '
             + hasta.strftime('%d/%m/%Y'))]


def _valor_evolucion(location_ids, metric, inicio, fin, moneda,
                      incluir_compras):
    """Valor de un tramo para el gráfico de evolución, leyendo SIEMPRE de las
    tablas reales (sin snapshots): un tramo puede ser un día suelto."""
    if metric == 'CONSOLIDATED':
        totales = _consolidado_por_periodo(location_ids, 'MONTHLY', inicio, fin,
                                           moneda,
                                           incluir_compras=incluir_compras)
    else:
        totales = _sumar_rango(location_ids, metric, 'MONTHLY', inicio, fin,
                               usar_snapshots=False)
    if metric == 'TRANSFERS':
        valor = Decimal(str(totales['record_count']))
    elif metric == 'CONSOLIDATED':
        valor = totales.get(f'amount_{moneda.lower()}', Decimal('0.00'))
    else:
        valor = _valor_con_respaldo(location_ids, metric, 'MONTHLY', inicio,
                                    fin, moneda, totales)
    return _redondear(valor)


def obtener_evolucion(location_ids, metric, period_type='MONTHLY',
                      period_start=None, moneda='USD', limite=6,
                      incluir_compras=True, desde=None, hasta=None):
    """Serie temporal para el gráfico de evolución.

    Con `desde`/`hasta` explícitos se grafica EXACTAMENTE ese rango (un punto
    por día, o el total si abarca más de 31 días) leyendo de las tablas
    reales: antes se graficaba siempre el período completo, de modo que cambiar
    el filtro no alteraba el gráfico. Sin rango se mantiene la serie de N
    períodos históricos del ancla."""
    metric = (metric or 'PURCHASES').upper()
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    ref_metric = 'PURCHASES' if metric == 'CONSOLIDATED' else metric

    if desde and hasta:
        return [{
            'label': etiqueta,
            'value': _valor_evolucion(location_ids, metric, inicio, fin,
                                      moneda, incluir_compras),
        } for inicio, fin, etiqueta in _segmentos_rango(desde, hasta)]

    ancla = _ancla_inicial(location_ids, ref_metric, period_type, period_start)
    disponibles = listar_periodos_disponibles(
        location_ids, ref_metric, period_type, limite=60)
    elegibles = sorted([d for d in disponibles if d <= ancla])[-max(1, limite):]
    if not elegibles:
        elegibles = [ancla]

    puntos = []
    for inicio in elegibles:
        fin = _fin_desde_inicio(period_type, inicio)
        if metric == 'CONSOLIDATED':
            totales = _consolidado_por_periodo(location_ids, period_type,
                                               inicio, fin, moneda,
                                               incluir_compras=incluir_compras)
        else:
            totales = _sumar_rango(location_ids, metric, period_type,
                                   inicio, fin)
        if metric == 'TRANSFERS':
            valor = Decimal(str(totales['record_count']))
        elif metric == 'CONSOLIDATED':
            # El consolidado ya se calculó en la moneda del reporte.
            valor = totales.get(f'amount_{moneda.lower()}', Decimal('0.00'))
        else:
            # Si la columna de esa moneda viene en 0 (snapshot viejo), se
            # recalcula con los datos reales del período.
            valor = _valor_con_respaldo(location_ids, metric, period_type,
                                        inicio, fin, moneda, totales)
        puntos.append({
            'label': _etiqueta_periodo(period_type, inicio, fin),
            'value': _redondear(valor),
        })
    return puntos


def _serie_detalle(reporte, moneda):
    """Datos del gráfico del reporte activo (proveedores, mermas, traslados o
    consolidado), en la moneda seleccionada. Los consumos no tienen desglose."""
    metric = reporte['filters']['metric']
    detalle = reporte.get('detail') or {}
    moneda = (moneda or 'USD').upper()

    if metric == 'PURCHASES':
        filas = detalle.get('por_proveedor') or []
        filas = [f for f in filas if f.get('monto') is not None]
        filas.sort(key=lambda f: -float(f['monto']))
        filas = filas[:8]
        if not filas:
            return None
        return {
            'titulo': 'Compras por proveedor', 'tipo': 'bar',
            'labels': [f['supplier_name'] for f in filas],
            'values': [float(f['monto']) for f in filas],
            'unidad': moneda,
        }

    if metric == 'WASTE':
        filas = detalle.get('mermas') or []
        filas = sorted(filas, key=lambda f: -float(f['cost']))[:8]
        if not filas:
            return None
        return {
            'titulo': 'Mermas del período (cada registro real)',
            'tipo': 'bar',
            'labels': [
                f"{f['date'].strftime('%d/%m/%Y')} {f['waste_type'] or 'Sin tipo'}"
                for f in filas
            ],
            'values': [float(f['cost']) for f in filas],
            'unidad': moneda,
        }

    if metric == 'TRANSFERS':
        por_tipo = detalle.get('por_tipo') or {}
        items = sorted(por_tipo.items(), key=lambda kv: -kv[1])
        if not items:
            return None
        return {
            'titulo': 'Traslados por tipo', 'tipo': 'doughnut',
            'labels': [k for k, _ in items],
            'values': [v for _, v in items],
        }

    if metric == 'CONSOLIDATED':
        consolidado = detalle.get('consolidado') or {}
        filas = consolidado.get('distribucion') or []
        if not filas:
            return None
        return {
            'titulo': 'Distribución del período — destino de la mercancía',
            'tipo': 'doughnut',
            'labels': [f['label'] for f in filas],
            # La dona muestra PORCENTAJES del destino de la compra, no montos
            # repetidos de la evolución lineal.
            'values': [float(f['pct']) for f in filas],
            'unidad': '%',
            'porcentaje': True,
            'detalle_montos': [{'label': f['label'],
                                'monto': float(f['monto'])}
                               for f in filas],
            'moneda_montos': consolidado.get('moneda', moneda),
        }

    return None


def _serie_ranking(ranking, moneda, metric='PURCHASES'):
    if not ranking:
        return None
    filas = sorted(ranking, key=lambda r: -float(r['total_base']))
    return {
        'titulo': ('Gastos operativos por sede' if metric == 'CONSOLIDATED'
                   else 'Ranking entre sedes'), 'tipo': 'ranking',
        'labels': [r['location_name'] for r in filas],
        'values': [float(r['total_base']) for r in filas],
        'unidad': (moneda or 'USD').upper(),
    }


def _retroceder_periodo(period_type, inicio, cantidad):
    """Inicio del período 'cantidad' períodos antes de 'inicio'."""
    if period_type == 'WEEKLY':
        return inicio - timedelta(days=7 * cantidad)
    if period_type == 'QUARTERLY':
        return _add_months(inicio, -3 * cantidad)
    if period_type == 'ANNUAL':
        return inicio.replace(year=inicio.year - cantidad)
    return _add_months(inicio, -cantidad)


def _gasto_por_categoria_rango(inicio, fin, moneda):
    """Categorías contables compradas dentro del tramo [inicio, fin], sin
    incluir nada fuera de él."""
    por_cat = {}
    for fila in obtener_gasto_por_categoria(inicio, fin):
        # Monto ya valorizado con la tasa del día de cada compra.
        por_cat[fila['category']] = fila['equivalente'].get(
            moneda, Decimal('0.00'))
    return por_cat


def obtener_gasto_categorias(period_type='MONTHLY', period_start=None,
                             moneda='USD', meses=6, desde=None, hasta=None):
    """Serie comparada de meses con el dinero REAL gastado POR CATEGORÍA
    contable (cantidad × precio de purchase_details). Las compras se muestran
    con el valor registrado en la moneda del reporte: el BS es el price_bs que
    se grabó con la tasa del día de cada compra. Devuelve etiquetas de períodos
    y N series apiladas (top categorías + 'Otros').

    Con `desde`/`hasta` explícitos se calcula UNA sola columna con lo comprado
    dentro del rango (antes siempre se traían los últimos 6 meses)."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    ancla = calcular_periodo(period_type,
                             period_start or current_ve_time().date())['period_start']

    columnas = []
    if desde and hasta:
        columnas.append({
            'label': ('Del ' + desde.strftime('%d/%m/%Y') + ' al '
                      + hasta.strftime('%d/%m/%Y')),
            'por_cat': _gasto_por_categoria_rango(desde, hasta, moneda),
        })
    else:
        for i in range(meses - 1, -1, -1):
            inicio = _retroceder_periodo(period_type, ancla, i)
            fin = _fin_desde_inicio(period_type, inicio)
            columnas.append({
                'label': _etiqueta_periodo(period_type, inicio, fin),
                'por_cat': _gasto_por_categoria_rango(inicio, fin, moneda),
            })

    totales_cat = {}
    for col in columnas:
        for cat, monto in col['por_cat'].items():
            totales_cat[cat] = totales_cat.get(cat, Decimal('0')) + monto
    ordenadas = sorted(totales_cat.items(), key=lambda kv: -float(kv[1]))

    top = ordenadas[:8]
    resto = Decimal('0.00')
    for _cat, monto in ordenadas[8:]:
        resto += monto
    if resto > 0:
        top.append(('Otros', resto))

    series = []
    for cat, _ in top:
        series.append({
            'name': cat,
            'values': [_redondear(col['por_cat'].get(cat, Decimal('0.00')))
                       for col in columnas],
        })
    totales = [sum((col['por_cat'].get(cat, Decimal('0.00'))
                    for cat, _ in top), Decimal('0.00'))
               for col in columnas]

    return {
        'labels': [col['label'] for col in columnas],
        'series': series,
        'totales': [_redondear(t) for t in totales],
        'moneda': moneda,
    }


def obtener_evolucion_gasto(period_type='MONTHLY', period_start=None,
                            moneda='USD', meses=6, desde=None, hasta=None):
    """Evolución REAL del dinero gastado (compras exactas) por período, desde
    purchase_details. Las compras se muestran con el valor registrado en la
    moneda del reporte (el BS es el price_bs de cada compra, grabado con la
    tasa del día de compra). Con `desde`/`hasta` explícitos grafica solo ese
    rango (un punto por día o el total), sin meses fuera del filtro."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    ancla = calcular_periodo(period_type,
                             period_start or current_ve_time().date())['period_start']

    if desde and hasta:
        puntos = []
        for inicio, fin, etiqueta in _segmentos_rango(desde, hasta):
            total = sum((fila['equivalente'].get(moneda, Decimal('0.00'))
                         for fila in obtener_gasto_por_categoria(inicio, fin)),
                        Decimal('0.00'))
            puntos.append({'label': etiqueta, 'value': _redondear(total)})
        return puntos

    puntos = []
    for i in range(meses - 1, -1, -1):
        inicio = _retroceder_periodo(period_type, ancla, i)
        fin = _fin_desde_inicio(period_type, inicio)
        total = Decimal('0.00')
        for fila in obtener_gasto_por_categoria(inicio, fin):
            # Monto ya valorizado con la tasa del día de cada compra: la serie
            # coincide con el KPI de compras (antes se reconvertía el Bs con la
            # tasa de cierre y la suma daba 210,71 en vez de 209,95).
            total += fila['equivalente'].get(moneda, Decimal('0.00'))
        puntos.append({
            'label': _etiqueta_periodo(period_type, inicio, fin),
            'value': _redondear(total),
        })
    return puntos


def construir_graficos(reporte, ranking, moneda='USD', incluir_compras=True,
                       desde=None, hasta=None):
    """Datos serializables (números sueltos) para los gráficos Chart.js de la
    pantalla: evolución temporal, desglose del reporte, gasto por categoría
    contable y ranking entre sedes. El dinero (compras/consolidado) sale de las
    tablas reales tal cual está en el sistema; el resto del cajón de
    resúmenes. Si incluir_compras es False las series de compras se omiten.

    Con `desde`/`hasta` explícitos TODOS los gráficos respetan ese rango: antes
    la evolución y las categorías mostraban siempre el período/meses completos.
    """
    metric = reporte['filters']['metric']
    if metric == 'PURCHASES' and incluir_compras:
        # Solo compras: dinero gastado compra por compra (tasa del día).
        evolucion = obtener_evolucion_gasto(
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda, desde=desde, hasta=hasta)
    else:
        # CONSOLIDATED: inversión real del período = compras a proveedores,
        # compra por compra con la tasa del día. Cocina y mermas no se suman
        # (son salidas de esa misma mercancía).
        evolucion = obtener_evolucion(
            reporte['filters']['location_ids'],
            metric,
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda,
            incluir_compras=incluir_compras,
            desde=desde, hasta=hasta)
    return {
        'metric': metric,
        'moneda': (moneda or 'USD').upper(),
        'evolucion': evolucion,
        'detalle': _serie_detalle(reporte, moneda),
        'gasto': (obtener_gasto_categorias(
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda, desde=desde, hasta=hasta) if incluir_compras
            else {'labels': [], 'series': [], 'totales': []}),
        'ranking': _serie_ranking(ranking, moneda, metric),
    }


def obtener_kpis(location_ids, period_type='MONTHLY', period_start=None,
                 moneda='USD', incluir_compras=True, desde=None, hasta=None):
    """KPIs del período con dinero REAL de las tablas del sistema (purchase_details,
    auditoría de consumo, mermas aprobadas y extravíos valorizados): Compras,
    Gastos de cocina, Mermas y pérdidas (mermas + pérdidas de traslado) y
    Traslados, cada uno con su variación contra el período anterior. Las compras se valoran con la tasa del día de cada compra
    (price_bs registrado); lo demás con la última tasa BCV del rango. No se
    calcula un 'costo operativo' residual: cada rubro se presenta transparente
    y los traslados son un indicador logístico independiente. Con
    incluir_compras=False el KPI de compras se omite."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    limites = _limites_rango(desde, hasta, location_ids, 'CONSOLIDATED')
    if limites:
        inicio, fin = limites
        duracion = (fin - inicio).days + 1
        previo_inicio, previo_fin = (inicio - timedelta(days=duracion),
                                     inicio - timedelta(days=1))
        marco = {'previous_start': previo_inicio, 'previous_end': previo_fin,
                 'label': ('Del ' + inicio.strftime('%d/%m/%Y') + ' al '
                           + fin.strftime('%d/%m/%Y')),
                 'previous_label': ('Del ' + previo_inicio.strftime('%d/%m/%Y')
                                    + ' al ' + previo_fin.strftime('%d/%m/%Y'))}
    else:
        ancla = _ancla_inicial(location_ids, 'PURCHASES', period_type,
                               period_start)
        marco = calcular_periodo(period_type, ancla)
        inicio, fin = ancla, _fin_desde_inicio(period_type, ancla)
        previo_inicio, previo_fin = marco['previous_start'], marco['previous_end']
        marco['label'] = _etiqueta_periodo(period_type, inicio, fin)
        marco['previous_label'] = _etiqueta_periodo(
            period_type, previo_inicio, previo_fin)
    orientacion = _orientacion_efectiva(location_ids, incluir_compras)

    def metricas_reales(desde, hasta):
        desde_dt = datetime.combine(desde, time.min)
        hasta_dt = datetime.combine(hasta, time.max)
        mermas = obtener_mermas_resumen(location_ids, desde_dt, hasta_dt)
        consumo = obtener_consumo_valorizado(location_ids, desde_dt, hasta_dt)
        datos = obtener_traslados_valorizados(location_ids, desde_dt, hasta_dt,
                                              orientacion)

        def convertir(buckets):
            total = _convertir_buckets(buckets, moneda, hasta_dt)
            return _redondear(total) if total is not None else Decimal('0.00')

        perdidas = convertir(datos['perdidas'])
        return {
            'compras': (_compras_en_moneda(desde_dt, hasta_dt, moneda)
                        if incluir_compras else Decimal('0.00')),
            'consumo': convertir(consumo['total']),
            'mermas_solo': convertir(mermas['total']),
            'perdidas': perdidas,
            # Las pérdidas de traslado son pérdida operativa de mercancía:
            # se analizan junto a las mermas, no como un rubro ajeno.
            'mermas': _redondear(convertir(mermas['total']) + perdidas),
            'direccional': _agrupar_direccional(datos['filas'], moneda,
                                                hasta_dt),
        }

    actual = metricas_reales(inicio, fin)
    anterior = metricas_reales(marco['previous_start'], marco['previous_end'])

    def estado(clave):
        act, ant = actual[clave], anterior[clave]
        return {
            'actual': _redondear(act),
            'anterior': _redondear(ant),
            'diferencia': _redondear(act - ant),
            'pct': (_redondear(((act - ant) / ant) * 100) if ant != 0 else None),
            'direccion': ('up' if act > ant else ('down' if act < ant else 'flat')),
        }

    if orientacion == SEDE_CENTRAL_ID:
        clave_flujo = 'enviados'
        flujo_actual = actual['direccional'][clave_flujo]
        flujo_anterior = anterior['direccional'][clave_flujo]
    else:
        # Sedes no centrales: lo que llegó a cualquiera de sus sedes visibles,
        # incluidos los movimientos entre ellas (internos). Antes solo se
        # contaban los recibidos de fuera y un ámbito multi-sede mostraba 0.
        clave_flujo = 'recibidos'
        flujo_actual = flujo_recibido_por_destino(actual['direccional'])
        flujo_anterior = flujo_recibido_por_destino(anterior['direccional'])
    f_act, f_ant = flujo_actual['cost'], flujo_anterior['cost']

    kpis = {
        'consumo_cocina': {'label': 'Gastos de cocina',
                           'metric': 'KITCHEN_CONSUMPTION',
                           **estado('consumo')},
        'mermas': {'label': 'Mermas y pérdidas', 'metric': 'WASTE',
                   'mermas_solo': _redondear(actual['mermas_solo']),
                   'perdidas_traslado': _redondear(actual['perdidas']),
                   **estado('mermas')},
        'traslados': {'label': ('Traslados enviados'
                                if clave_flujo == 'enviados'
                                else 'Traslados recibidos'),
                      'metric': 'TRANSFERS', 'monetizado': True,
                      'actual': _redondear(f_act),
                      'anterior': _redondear(f_ant),
                      'diferencia': _redondear(f_act - f_ant),
                      'pct': (_redondear(((f_act - f_ant) / f_ant) * 100)
                              if f_ant != 0 else None),
                      'direccion': ('up' if f_act > f_ant
                                    else ('down' if f_act < f_ant else 'flat')),
                      'conteo': flujo_actual['conteo'],
                      'quantity': flujo_actual['quantity']},
    }
    if incluir_compras:
        kpis['compras'] = {'label': 'Compras', 'metric': 'PURCHASES',
                           **estado('compras')}

    return {
        'moneda': moneda,
        'period': {
            'start': inicio,
            'end': fin,
            'label': marco['label'],
            'previous_label': marco['previous_label'],
        },
        'kpis': kpis,
        'direccional': actual['direccional'],
        'perdidas': actual['perdidas'],
    }


def obtener_anclas_selector(location_ids, metric, period_type, limite=12):
    """Fechas de inicio disponibles en el cajón para el selector de período."""
    return listar_periodos_disponibles(location_ids, metric, period_type, limite)


def obtener_fechas_disponibles(location_ids, metric, period_type):
    """Fechas donde existen registros reales (compras, consumo, mermas,
    traslados) para las sedes dadas, ascendentes. El rango desde/hasta solo
    permite elegir estas fechas, sin depender de que el cajón esté lleno."""
    return fechas_con_registros(location_ids, metric)


def obtener_anclas_mes(location_ids, metric, limite=12):
    """Inicios de mes con registros REALES para las sedes dadas, del más
    reciente al más antiguo. Alimenta el selector de período del Panel de
    Finanzas sin depender de que el cajón (statistics_snapshots) esté lleno."""
    fechas = fechas_con_registros(location_ids, metric)
    meses = sorted({date(f.year, f.month, 1) for f in fechas}, reverse=True)
    return meses[:max(1, limite)]