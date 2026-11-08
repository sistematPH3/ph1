from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.analytics.repositories.analysis_reports_repository import (
    fechas_con_registros,
    hay_snapshots_metrico,
    listar_periodos_disponibles,
    obtener_compras_consolidado,
    obtener_compras_por_moneda,
    obtener_compras_por_proveedor,
    obtener_consumo_valorizado,
    obtener_gasto_por_categoria,
    obtener_mermas_detalle,
    obtener_mermas_resumen,
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


def _convertir_monto(monto, origen, destino, fecha):
    """Convierte 'monto' de su moneda de origen a la del reporte con la tasa
    BCV vigente en 'fecha'. Retorna None si la tasa necesaria no existe
    (por ejemplo, EUR cuando no se han cargado tasas EUR)."""
    monto = Decimal(str(monto or 0))
    if not monto:
        return Decimal('0.00')
    origen = (origen or 'USD').upper()
    destino = (destino or 'USD').upper()
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
    """Suma los montos en USD/BS/EUR del dict convertiendo cada uno a la moneda
    del reporte. Retorna None si alguna moneda con monto no tiene tasa."""
    total = Decimal('0.00')
    for moneda in MONEDAS:
        monto = buckets.get(moneda, Decimal('0.00')) or Decimal('0.00')
        if not monto:
            continue
        convertido = _convertir_monto(monto, moneda, destino, fecha)
        if convertido is None:
            return None
        total += convertido
    return total


def _monto_en_moneda(buckets, moneda, fecha=None):
    """Monto de COMPRAS en la moneda del reporte usando el valor REGISTRADO:
    el BS de cada detalle quedó grabado en price_bs con la tasa del día de la
    compra (Purchase.exchange_rate), así que se muestra ese monto sin re-valuarlo
    con la tasa del cierre. Si la moneda elegida no tiene valor registrado, se
    intenta convertir con la tasa del período; sin tasa (EUR) da 0.00."""
    moneda = (moneda or 'USD').upper()
    buckets = buckets or {}
    registrado = buckets.get(moneda, Decimal('0.00')) or Decimal('0.00')
    if registrado:
        return _redondear(registrado)
    total = _convertir_buckets(buckets, moneda, fecha)
    return _redondear(total) if total is not None else Decimal('0.00')


def _convertir_compra_a_moneda(fila, moneda):
    """Equivalente de una compra a la moneda del reporte usando la tasa del día
    que el sistema registró (exchange_rate = Bs por unidad de la moneda de la
    compra). None si no hay tasa disponible (p. ej. EUR sin tasa cargada)."""
    c = (fila.get('currency') or 'USD').upper()
    monto = fila.get('total_' + c.lower(), Decimal('0.00')) or Decimal('0.00')
    if not monto or c == moneda:
        return monto
    tasa = Decimal(str(fila.get('exchange_rate') or 0))
    if not tasa:
        return None
    if c == 'USD' and moneda == 'BS':
        return monto * tasa
    if c == 'BS' and moneda == 'USD':
        return monto / tasa
    if c == 'EUR' and moneda == 'BS':
        return monto * tasa
    if c == 'BS' and moneda == 'EUR':
        return monto / tasa
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
    for fila in obtener_compras_por_moneda(desde_dt, hasta_dt):
        c = fila['currency']
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
    ref = ref_date or date.today()
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


def _sumar_rango(location_ids, metric, period_type, desde, hasta):
    """Totales del rango. Si el cajón (statistics_snapshots) tiene resúmenes
    para la métrica los suma; si está vacío (en la práctica nadie lo llena)
    lee de las tablas REALES: compras, consumo de cocina, mermas aprobadas y
    traslados valorizados."""
    metric = (metric or 'PURCHASES').upper()
    if not hay_snapshots_metrico(location_ids, metric):
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
    for clave in ('amount_usd', 'amount_bs', 'amount_eur', 'quantity'):
        totales[clave] = _redondear(totales[clave])
    return totales


def _consolidado_por_periodo(location_ids, period_type, desde, hasta,
                             moneda='USD', incluir_compras=True):
    """Consolidado financiero del rango con datos REALES, convertido a la moneda
    seleccionada del reporte (USD→Bs/EUR con la tasa BCV del período):
    Compras − Consumo de cocina − Mermas − Pérdidas en traslado."""
    consolidado = consolidado_financiero(location_ids, desde, hasta, moneda,
                                          incluir_compras=incluir_compras)
    monto = consolidado['resultado']
    return {
        'amount_usd': monto,
        'amount_bs': monto,
        'amount_eur': monto,
        'quantity': Decimal('0.00'),
        'record_count': 0,
    }


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


def _marco_desde_filtros(filtros, location_ids, ref_metric):
    """Marco temporal del reporte. Con desde/hasta definidos usa el rango libre
    exacto; sin ellos deriva el período del tipo seleccionado (ancla del cajón)."""
    if filtros.desde and filtros.hasta:
        inicio, fin = filtros.desde, filtros.hasta
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

    if metric == 'CONSOLIDATED':
        actual = _consolidado_por_periodo(efectivas, period_type, inicio, fin,
                                          moneda, incluir_compras=incluir_compras)
        anterior = _consolidado_por_periodo(efectivas, period_type,
                                            previo_inicio, previo_fin, moneda,
                                            incluir_compras=incluir_compras)
    else:
        actual = _sumar_rango(efectivas, metric, period_type, inicio, fin)
        anterior = _sumar_rango(efectivas, metric, period_type,
                                previo_inicio, previo_fin)
    comparativo = calcular_comparativo(actual, anterior, moneda)

    detalle = _detalle_metric(efectivas, metric, period_type,
                              datetime.combine(inicio, time.min),
                              datetime.combine(fin, time.max),
                              moneda,
                              incluir_compras=incluir_compras)

    return {
        'filters': {
            'location_id': filtros.location_id,
            'location_ids': efectivas,
            'metric': metric,
            'period_type': period_type,
            'moneda': moneda,
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


def _detalle_metric(location_ids, metric, period_type, inicio, fin,
                    moneda='USD', incluir_compras=True):
    if metric == 'PURCHASES':
        filas = obtener_compras_por_proveedor(inicio, fin)
        for f in filas:
            f['monto'] = _monto_en_moneda(
                {'USD': f.get('total_usd', Decimal('0.00')),
                 'BS': f.get('total_bs', Decimal('0.00')),
                 'EUR': f.get('total_eur', Decimal('0.00'))}, moneda, fin)
            f['moneda'] = moneda
        return {'por_proveedor': filas}
    if metric == 'KITCHEN_CONSUMPTION':
        return {'registros': obtener_resumen_consumo(location_ids, inicio, fin)}
    if metric == 'WASTE':
        registros = obtener_mermas_detalle(location_ids, inicio, fin)
        for r in registros:
            r['cost_original'] = r['cost']
            r['origin_currency'] = r['currency']
            convertido = _convertir_monto(
                r['cost_original'], r['origin_currency'], moneda, fin)
            r['cost'] = _redondear(convertido) if convertido is not None else Decimal('0.00')
            r['currency'] = moneda
        return {'mermas': registros}
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
        recibido = obtener_recibido_por_insumo(location_ids, inicio, fin,
                                               orientacion)
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
        return resumen
    if metric == 'CONSOLIDATED':
        return {'consolidado': consolidado_financiero(location_ids, inicio, fin,
                                                      moneda,
                                                      incluir_compras=incluir_compras)}
    return {}


def _detalles_extravio(location_ids, desde, hasta):
    """Detalle de extravíos del rango valorizados a costo (último costo de
    compra por producto/lote). Incluye la sede de origen del movimiento para el
    desglose 'por sede'. El costo se expresa en USD (luego se convierte a la
    moneda del reporte en quien lo consume)."""
    datos = obtener_traslados_valorizados(location_ids, desde, hasta)
    filas = []
    for f in datos['filas']:
        if not f['missing_quantity']:
            continue
        costo = _convertir_buckets(f['perdidas'], 'USD', hasta)
        filas.append({
            'product_id': None,
            'quantity': f['missing_quantity'],
            'costo': _redondear(costo) if costo is not None else Decimal('0.00'),
            'buckets': dict(f['perdidas']),
            'location_id': f['origin_id'] or f['destination_id'],
            'location_name': f['origin_name'] or f['destination_name'],
        })
    return filas


def _cubo_direccion_vacio():
    return {'conteo': 0, 'quantity': Decimal('0.00'),
            'buckets': _bucket_vacio(), 'cost': Decimal('0.00')}


def _agrupar_direccional(filas, moneda, fecha):
    """Agrupa las filas de obtener_traslados_valorizados por dirección y
    convierte el costo a la moneda del reporte con la tasa vigente en 'fecha'."""
    base = {d: {'conteo': 0, 'quantity': Decimal('0.00'),
                'buckets': _bucket_vacio()}
            for d in ('enviados', 'recibidos', 'internos')}
    for fila in filas:
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
    internos. Cada dirección trae conteo (nº de traslados), quantity
    (mercancía movida) y cost (valor convertido). Con orientacion_id (la
    Central para quien la gestiona) la dirección se narra desde esa sede."""
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
    return {
        'moneda': moneda,
        'enviados': direccional['enviados'],
        'recibidos': direccional['recibidos'],
        'internos': direccional['internos'],
        'total': total,
        'movimientos': movimientos,
        'perdidas': _redondear(perdidas),
        'extravios_quantity': datos['extravios_quantity'],
    }


def consolidado_financiero(location_ids, desde, hasta, moneda='USD',
                           incluir_compras=True):
    """Gasto REAL del rango convertido a la moneda seleccionada del reporte
    (por defecto USD): por concepto (compras, consumo, mermas, pérdidas en
    traslados), por categoría contable, por sede y 'por moneda' (en qué moneda
    se compró más). Las compras se valoran con la tasa del día de cada compra
    (el BS registrado en price_bs); consumo/mermas/pérdidas con la última tasa
    BCV del período. Si incluir_compras es False (sedes que no gestionan la
    Central) las compras se eliminan por completo y el resultado pasa a medirse
    por el flujo de traslados: −(Consumo + Mermas + Pérdidas en traslados)."""
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
            por_categoria[cat][m] += linea['buckets'].get(m, Decimal('0.00'))
    compras_monto = (_compras_en_moneda(desde_dt, hasta_dt, moneda)
                     if incluir_compras else Decimal('0.00'))

    perdidas = _bucket_vacio()
    perdidas_buckets_reales = _bucket_vacio()
    perdidas_por_sede = {}
    for extra in _detalles_extravio(location_ids, desde_dt, hasta_dt):
        perdidas['USD'] += extra['costo']
        for m in MONEDAS:
            perdidas_buckets_reales[m] += extra['buckets'].get(
                m, Decimal('0.00'))
        sede = extra['location_name']
        perdidas_por_sede.setdefault(sede, _bucket_vacio())
        perdidas_por_sede[sede]['USD'] += extra['costo']

    por_concepto = []
    if incluir_compras:
        por_concepto.append({'concepto': 'Compras', 'tipo': 'egreso',
                             'monto': compras_monto,
                             'buckets': compras_totales})
    por_concepto.extend([
        {'concepto': 'Consumo de cocina', 'tipo': 'egreso',
         'monto': convertir(consumo['total']),
         'buckets': {m: _redondear(consumo['total'].get(m, Decimal('0.00')))
                     for m in MONEDAS}},
        {'concepto': 'Mermas', 'tipo': 'egreso',
         'monto': convertir(mermas['total']),
         'buckets': {m: _redondear(mermas['total'].get(m, Decimal('0.00')))
                     for m in MONEDAS}},
        {'concepto': 'Pérdidas en traslados', 'tipo': 'egreso',
         'monto': convertir(perdidas),
         'buckets': {m: _redondear(v) for m, v in
                     perdidas_buckets_reales.items()}},
    ])

    egresos = sum(fila['monto'] for fila in por_concepto
                  if fila['concepto'] != 'Compras')
    resultado = compras_monto - egresos

    por_categoria_filas = [
        {'category': cat, 'monto': _monto_en_moneda(b, moneda, hasta_dt)}
        for cat, b in por_categoria.items()
    ]
    por_categoria_filas.sort(key=lambda f: -float(f['monto']))

    por_sede_map = {}
    for fuente in (mermas['por_sede'], consumo['por_sede'], perdidas_por_sede):
        for sede, valores in fuente.items():
            por_sede_map.setdefault(sede, _bucket_vacio())
            for m in MONEDAS:
                por_sede_map[sede][m] += valores.get(m, Decimal('0.00'))
    por_sede = [{'sede': sede, 'monto': convertir(val)}
                for sede, val in por_sede_map.items()]
    if incluir_compras and compras_monto:
        por_sede.append({'sede': 'Compras Central', 'monto': compras_monto})
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
        'resultado': _redondear(resultado),
    }


def obtener_metrica_por_sede(location_ids, metric, period_type, inicio, fin,
                             moneda='USD', incluir_compras=True):
    """Un renglón por sede para el ranking y la comparativa lateral."""
    nombres = obtener_nombres_sedes(location_ids)
    renglones = []
    for loc_id in location_ids:
        if metric == 'CONSOLIDATED':
            totales = _consolidado_por_periodo([loc_id], period_type,
                                               inicio, fin, moneda,
                                               incluir_compras=incluir_compras)
        else:
            totales = _sumar_rango([loc_id], metric, period_type,
                                   inicio, fin)
        snap = obtener_snapshot(loc_id, metric, period_type, inicio)
        if snap is None:
            snap = obtener_snapshot(loc_id, 'PURCHASES', period_type, inicio)
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
            'total_base': _redondear(totales[f'amount_{moneda.lower()}']),
        })
    return renglones


def obtener_ranking(location_ids, metric, period_start=None, period_type='MONTHLY',
                    moneda='USD', incluir_compras=True, desde=None, hasta=None):
    """Ranking de sedes para una métrica, ordenado por monto en la moneda base
    (mayor primero) con su comparativa contra el período anterior."""
    if desde and hasta:
        inicio, fin = desde, hasta
        duracion = (hasta - desde).days + 1
        previo_inicio, previo_fin = (inicio - timedelta(days=duracion),
                                     inicio - timedelta(days=1))
    else:
        ancla = _ancla_inicial(location_ids, metric, period_type, period_start)
        inicio, fin = ancla, _fin_desde_inicio(period_type.upper(), ancla)
        marco = calcular_periodo(period_type.upper(), ancla)
        previo_inicio, previo_fin = (marco['previous_start'],
                                     marco['previous_end'])

    renglones = obtener_metrica_por_sede(location_ids, metric, period_type.upper(),
                                         inicio, fin, moneda,
                                         incluir_compras=incluir_compras)
    monto_key = f'amount_{moneda.lower()}'
    for renglon in renglones:
        previo = _sumar_rango([renglon['location_id']], metric,
                              period_type.upper(), previo_inicio, previo_fin)
        anterior_m = previo[monto_key]
        actual_m = renglon[monto_key]
        renglon['anterior'] = _redondear(anterior_m)
        renglon['diferencia'] = _redondear(actual_m - anterior_m)
        renglon['pct'] = (_redondear(((actual_m - anterior_m) / anterior_m) * 100)
                          if anterior_m != 0 else None)

    renglones.sort(key=lambda r: -float(r['total_base']))
    return renglones


def obtener_evolucion(location_ids, metric, period_type='MONTHLY',
                      period_start=None, moneda='USD', limite=6,
                      incluir_compras=True):
    """Serie temporal de los N períodos históricos (hasta e incluyendo el ancla)
    para el gráfico de evolución. Lee del cajón, igual que los KPIs. Los
    traslados se grafican por cantidad de registros; lo demás por monto en la
    moneda base del reporte."""
    metric = (metric or 'PURCHASES').upper()
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    ref_metric = 'PURCHASES' if metric == 'CONSOLIDATED' else metric

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
        else:
            valor = totales.get(f'amount_{moneda.lower()}', Decimal('0.00'))
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
        filas = consolidado.get('por_concepto') or []
        if not filas:
            return None
        return {
            'titulo': 'Consolidado del período',
            'tipo': 'doughnut',
            'labels': [f['concepto'] for f in filas],
            'values': [float(f['monto']) for f in filas],
            'unidad': consolidado.get('moneda', moneda),
        }

    return None


def _serie_ranking(ranking, moneda):
    if not ranking:
        return None
    filas = sorted(ranking, key=lambda r: -float(r['total_base']))
    return {
        'titulo': 'Ranking entre sedes', 'tipo': 'ranking',
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


def obtener_gasto_categorias(period_type='MONTHLY', period_start=None,
                             moneda='USD', meses=6):
    """Serie comparada de meses con el dinero REAL gastado POR CATEGORÍA
    contable (cantidad × precio de purchase_details). Las compras se muestran
    con el valor registrado en la moneda del reporte: el BS es el price_bs que
    se grabó con la tasa del día de cada compra. Devuelve etiquetas de períodos
    y N series apiladas (top categorías + 'Otros')."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    ancla = calcular_periodo(period_type,
                             period_start or date.today())['period_start']

    columnas = []
    for i in range(meses - 1, -1, -1):
        inicio = _retroceder_periodo(period_type, ancla, i)
        fin = _fin_desde_inicio(period_type, inicio)
        fin_dt = datetime.combine(fin, time.max)
        por_cat = {}
        for fila in obtener_gasto_por_categoria(inicio, fin):
            buckets = {'USD': fila['total_usd'], 'BS': fila['total_bs'],
                       'EUR': fila['total_eur']}
            por_cat[fila['category']] = _monto_en_moneda(buckets, moneda, fin_dt)
        columnas.append({
            'label': _etiqueta_periodo(period_type, inicio, fin),
            'por_cat': por_cat,
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
                            moneda='USD', meses=6):
    """Evolución REAL del dinero gastado (compras exactas) por período, desde
    purchase_details. Las compras se muestran con el valor registrado en la
    moneda del reporte (el BS es el price_bs de cada compra, grabado con la
    tasa del día de compra)."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    ancla = calcular_periodo(period_type,
                             period_start or date.today())['period_start']

    puntos = []
    for i in range(meses - 1, -1, -1):
        inicio = _retroceder_periodo(period_type, ancla, i)
        fin = _fin_desde_inicio(period_type, inicio)
        fin_dt = datetime.combine(fin, time.max)
        total = Decimal('0.00')
        for fila in obtener_gasto_por_categoria(inicio, fin):
            buckets = {'USD': fila['total_usd'], 'BS': fila['total_bs'],
                       'EUR': fila['total_eur']}
            total += _monto_en_moneda(buckets, moneda, fin_dt)
        puntos.append({
            'label': _etiqueta_periodo(period_type, inicio, fin),
            'value': _redondear(total),
        })
    return puntos


def construir_graficos(reporte, ranking, moneda='USD', incluir_compras=True):
    """Datos serializables (números sueltos) para los gráficos Chart.js de la
    pantalla: evolución temporal, desglose del reporte, gasto por categoría
    contable y ranking entre sedes. El dinero (compras/consolidado) sale de las
    tablas reales tal cual está en el sistema; el resto del cajón de
    resúmenes. Si incluir_compras es False las series de compras se omiten."""
    metric = reporte['filters']['metric']
    if metric in ('PURCHASES', 'CONSOLIDATED') and incluir_compras:
        evolucion = obtener_evolucion_gasto(
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda)
    else:
        evolucion = obtener_evolucion(
            reporte['filters']['location_ids'],
            metric,
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda,
            incluir_compras=incluir_compras)
    return {
        'metric': metric,
        'moneda': (moneda or 'USD').upper(),
        'evolucion': evolucion,
        'detalle': _serie_detalle(reporte, moneda),
        'gasto': (obtener_gasto_categorias(
            reporte['filters']['period_type'],
            reporte['period']['start'],
            moneda) if incluir_compras
            else {'labels': [], 'series': [], 'totales': []}),
        'ranking': _serie_ranking(ranking, moneda),
    }


def obtener_kpis(location_ids, period_type='MONTHLY', period_start=None,
                 moneda='USD', incluir_compras=True, desde=None, hasta=None):
    """KPIs del período con dinero REAL de las tablas del sistema (purchase_details,
    auditoría de consumo, mermas aprobadas y extravíos valorizados): Compras,
    Consumo, Mermas, Traslados y Costo operativo, cada uno con su variación
    contra el período anterior. Las compras se valoran con la tasa del día de
    cada compra (price_bs registrado); lo demás con la última tasa BCV del rango.
    Con incluir_compras=False (sedes que no gestionan la Central) el KPI de
    compras se omite y el costo operativo se mide por el flujo de traslados:
    −(Consumo + Mermas + Pérdidas en traslados)."""
    period_type = (period_type or 'MONTHLY').upper()
    moneda = (moneda or 'USD').upper()
    if moneda not in MONEDAS:
        moneda = 'USD'
    if desde and hasta:
        inicio, fin = desde, hasta
        duracion = (hasta - desde).days + 1
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

        return {
            'compras': (_compras_en_moneda(desde_dt, hasta_dt, moneda)
                        if incluir_compras else Decimal('0.00')),
            'consumo': convertir(consumo['total']),
            'mermas': convertir(mermas['total']),
            'perdidas': convertir(datos['perdidas']),
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

    if incluir_compras:
        costo = consolidado_financiero(location_ids, inicio, fin, moneda)['resultado']
        costo_anterior = consolidado_financiero(
            location_ids, marco['previous_start'], marco['previous_end'], moneda
        )['resultado']
    else:
        # Costo operativo de sedes no centrales: el egreso propio (consumo,
        # mermas y pérdidas en traslados) se mide contra el flujo de traslados
        # recibido, sin compras de por medio.
        costo = -(actual['consumo'] + actual['mermas'] + actual['perdidas'])
        costo_anterior = -(anterior['consumo'] + anterior['mermas']
                           + anterior['perdidas'])
    costo_operativo = {
        'actual': _redondear(costo),
        'anterior': _redondear(costo_anterior),
        'diferencia': _redondear(costo - costo_anterior),
        'pct': (_redondear(((costo - costo_anterior) / costo_anterior) * 100)
                if costo_anterior != 0 else None),
        'direccion': ('down' if costo < costo_anterior
                      else ('up' if costo > costo_anterior else 'flat')),
        'incluye_perdidas_traslado': actual['perdidas'],
        'medido_por_compras': incluir_compras,
    }

    clave_flujo = ('enviados' if orientacion == SEDE_CENTRAL_ID
                   else 'recibidos')
    flujo_actual = actual['direccional'][clave_flujo]
    flujo_anterior = anterior['direccional'][clave_flujo]
    f_act, f_ant = flujo_actual['cost'], flujo_anterior['cost']

    kpis = {
        'consumo_cocina': {'label': 'Gastos de cocina',
                           'metric': 'KITCHEN_CONSUMPTION',
                           **estado('consumo')},
        'mermas': {'label': 'Mermas', 'metric': 'WASTE',
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
        'costo_operativo': {'label': 'Costo operativo',
                            'metric': 'OPERATING_COST',
                            **costo_operativo},
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