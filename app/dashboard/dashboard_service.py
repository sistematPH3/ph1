from datetime import date as date_cls, datetime as datetime_cls, time as time_cls, timedelta

from app.extensions import db
from app.models import Movement, MovementDetail, Product, Location
from app.logistics.services.movement_list_service import get_movement_list_context
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard

STATUS_DISPLAY = {
    'EN_TRANSITO':       {'label': 'En Tránsito', 'cls': 'dash-badge-success'},
    'COMPLETADO':        {'label': 'Completado',  'cls': 'dash-badge-info'},
    'CANCELADO_EMISOR':  {'label': 'Cancelado',   'cls': 'dash-badge-danger'},
}

_MESES_ES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
             'julio', 'agosto', 'septiembre', 'octubre', 'noviembre',
             'diciembre']


def _etiqueta_ancla(fecha):
    """Etiqueta legible de un ancla (inicio de período), p. ej. 'Septiembre 2026'."""
    return '%s %s' % (_MESES_ES[fecha.month - 1].capitalize(), fecha.year)


def _sumar_meses(fecha, n):
    """El primer día del mes desplazado n meses desde fecha."""
    total = fecha.month - 1 + n
    return date_cls(fecha.year + total // 12, total % 12 + 1, 1)


def _ids_de_sedes(user):
    return [loc.id for loc in getattr(user, 'locations', [])]


def get_recent_movements(current_user, limit=5):
    """Últimos traslados que involucran las sedes del usuario."""
    sedes = _ids_de_sedes(current_user)
    if not sedes:
        return []

    movs = (
        Movement.query
        .filter(Movement.status.in_(['EN_TRANSITO', 'COMPLETADO', 'CANCELADO_EMISOR']))
        .filter(
            (Movement.origin_location_id.in_(sedes)) |
            (Movement.destination_location_id.in_(sedes))
        )
        .order_by(Movement.date.desc())
        .limit(limit)
        .all()
    )

    loc_map = {loc.id: loc for loc in Location.query.all()}
    rows = []
    for m in movs:
        origin = loc_map.get(m.origin_location_id)
        dest = loc_map.get(m.destination_location_id)
        display = STATUS_DISPLAY.get(m.status, {'label': m.status or '—', 'cls': 'dash-badge-secondary'})
        rows.append({
            'id': m.id,
            'date': m.date,
            'status_label': display['label'],
            'status_cls': display['cls'],
            'origin': origin.name if origin else 'Sede #%s' % m.origin_location_id,
            'destination': dest.name if dest else 'Sede #%s' % m.destination_location_id,
            'num_products': len(m.details),
            'total_qty': float(sum(float(d.quantity or 0) for d in m.details)),
        })
    return rows


def get_expiring_lots(current_user, limit=5, horizon_days=90):
    """Lotes recibidos (COMPLETADO) en las sedes del usuario que vencen pronto."""
    sedes = _ids_de_sedes(current_user)
    if not sedes:
        return []

    today = date_cls.today()
    limit_date = today + timedelta(days=horizon_days)

    rows = (
        db.session.query(MovementDetail, Product, Location)
        .join(Movement, MovementDetail.movement_id == Movement.id)
        .join(Product, MovementDetail.product_id == Product.id)
        .join(Location, Movement.destination_location_id == Location.id)
        .filter(
            Movement.status == 'COMPLETADO',
            MovementDetail.expiration_date.isnot(None),
            MovementDetail.expiration_date >= today,
            MovementDetail.expiration_date <= limit_date,
            Movement.destination_location_id.in_(sedes),
        )
        .order_by(MovementDetail.expiration_date.asc())
        .limit(limit)
        .all()
    )

    lots = []
    for det, prod, loc in rows:
        days = (det.expiration_date - today).days
        lots.append({
            'product': prod.name or 'Insumo',
            'lot': det.lot_number or 'N/A',
            'location': loc.name if loc else 'Sede',
            'expiration': det.expiration_date,
            'quantity': float(det.quantity or 0),
            'unit': prod.unit_of_measure or '',
            'days': days,
            'critical': days <= 30,
        })
    return lots


def get_subgerente_context(current_user):
    """Contexto completo del panel de Sub-Gerencia."""
    alarmas = obtener_alarmas_para_dashboard()
    movimientos = get_movement_list_context(current_user)

    return {
        'alarmas': alarmas,
        'en_camino_count': len(movimientos["en_camino"]),
        'por_recibir_count': len(movimientos["por_recibir"]),
        'critical_count': len(alarmas),
        'critical_stock': alarmas,
        'recent_movements': get_recent_movements(current_user),
'expiring_lots': get_expiring_lots(current_user),
    }


def get_finance_dashboard_context(current_user, sede_id=None, period_start=None,
                                  alarmas=None):
    """Contexto del Panel de Finanzas: KPIs del mes, ranking y filtros de
    sedes/período. Quien no gestiona la sede Central no ve compras; el ranking
    se mide por traslados. Con sede_id se acota el panel a una sede; con
    period_start se consulta otro período (inicio de un ancla). Añade el
    panorama del período: evolución de egresos (6 meses de datos reales),
    resumen (promedio diario, mermas %, costo por traslado, lotes/alertas) y
    top de compras por categoría si administra la Central."""
    from app.analytics.services import analysis_reports_service as reports_svc
    from app.analytics.repositories.analysis_reports_repository import (
        obtener_sedes_opciones,
    )

    permitidas, _ = reports_svc.queda_reporte_usuario_autorizado(current_user.id)
    if sede_id is not None and sede_id in permitidas:
        sede_ids = [sede_id]
    else:
        sede_ids = list(permitidas)
    hoy = period_start or date_cls.today()
    ver_compras = reports_svc.usuario_administra_central(current_user.id)
    metric_panel = 'PURCHASES' if ver_compras else 'TRANSFERS'
    kpis = reports_svc.obtener_kpis(sede_ids, 'MONTHLY', hoy, 'USD',
                                    incluir_compras=ver_compras)
    ranking = reports_svc.obtener_ranking(sede_ids, metric_panel, hoy,
                                          'MONTHLY', 'USD',
                                          incluir_compras=ver_compras)
    anclas = _anclas_reales(sede_ids, ver_compras, 12)
    periodo = kpis['period']
    traslados_mes = reports_svc.obtener_traslados_direccional(
        sede_ids,
        datetime_cls.combine(periodo['start'], time_cls.min),
        datetime_cls.combine(periodo['end'], time_cls.max),
        'USD')
    return {
        'kpis_mes': kpis,
        'ranking_mes': (ranking or [])[:3],
        'anclas_mes': anclas,
        'periodos_mes': [{'valor': a, 'etiqueta': _etiqueta_ancla(a)}
                         for a in anclas],
        'es_multisede': len(permitidas) >= 2,
        'sedes_opciones': obtener_sedes_opciones(current_user.id),
        'sede_actual': sede_id if sede_id in permitidas else None,
        'periodo_actual': period_start,
        'ver_compras': ver_compras,
        'metric_panel': metric_panel,
        'traslados_mes': traslados_mes,
        'traslados_direccion_principal': 'recibidos',
        'evolucion_mes': _evolucion_egresos(sede_ids, periodo['start'],
                                            ver_compras),
        'resumen_mes': _resumen_periodo(sede_ids, periodo, kpis,
                                        traslados_mes, ver_compras,
                                        current_user, alarmas=alarmas),
        'categorias_mes': (_categorias_compras(sede_ids, periodo['start'])
                           if ver_compras else []),
    }


def _anclas_reales(sede_ids, ver_compras, limite=12):
    """Inicios de mes con actividad real en el alcance del usuario: las compras
    (Central) o, en sedes, consumo de cocina + mermas + traslados."""
    from app.analytics.services import analysis_reports_service as reports_svc
    metricas = (['PURCHASES'] if ver_compras
                else ['KITCHEN_CONSUMPTION', 'WASTE', 'TRANSFERS'])
    fechas = set()
    for metrica in metricas:
        fechas.update(reports_svc.fechas_con_registros(sede_ids, metrica))
    meses = sorted({fecha.replace(day=1) for fecha in fechas}, reverse=True)
    return meses[:max(1, limite)]


def _egresos_del_periodo(sede_ids, inicio, fin, ver_compras):
    """Total gastado del rango según datos reales (incluye compras solo si se
    administra la Central): Compras + Consumo + Mermas + Pérdidas."""
    from app.analytics.services import analysis_reports_service as reports_svc
    cons = reports_svc.consolidado_financiero(
        sede_ids, inicio, fin, 'USD', incluir_compras=ver_compras)
    return sum(fila['monto'] for fila in cons['por_concepto'])


def _evolucion_egresos(sede_ids, ancla, ver_compras, meses=6):
    """Egresos mensuales reales de los últimos `meses` meses cerrando en el
    mes del ancla (de más antiguo a más reciente), para la gráfica."""
    ancla = ancla.replace(day=1)
    filas = []
    for i in range(meses - 1, -1, -1):
        mes = _sumar_meses(ancla, -i)
        fin = _sumar_meses(mes, 1) - timedelta(days=1)
        filas.append({
            'mes': mes,
            'etiqueta': _MESES_ES[mes.month - 1].capitalize(),
            'monto': _egresos_del_periodo(sede_ids, mes, fin, ver_compras),
        })
    return filas


def _resumen_periodo(sede_ids, periodo, kpis, traslados_mes, ver_compras,
                     user, alarmas=None):
    """Estadísticas generales del período: días, promedio diario, mermas sobre
    el egreso, costo por traslado, alarmas de stock y lotes por vencer."""
    inicio, fin = periodo['start'], periodo['end']
    dias = (fin - inicio).days + 1
    egresos = _egresos_del_periodo(sede_ids, inicio, fin, ver_compras)
    mermas = kpis['kpis']['mermas']['actual']
    mermas_pct = (float(mermas) / float(egresos) * 100
                  if egresos else None)
    traslado_total = (traslados_mes or {}).get('total') or {}
    conteo = traslado_total.get('conteo') or 0
    costo = traslado_total.get('cost') or 0
    costo_por_traslado = (costo / conteo if conteo else 0)
    lotes = get_expiring_lots(user, limit=60, horizon_days=90)
    return {
        'dias': dias,
        'egresos': egresos,
        'promedio_diario': (egresos / dias if dias else 0),
        'mermas_pct': (round(mermas_pct, 2) if mermas_pct is not None
                       else None),
        'costo_por_traslado': costo_por_traslado,
        'conteo_traslados': conteo,
        'alarmas': len(alarmas or []),
        'lotes': {
            'count': len(lotes),
            'criticos': sum(1 for l in lotes if l['critical']),
            'proximo': (lotes[0]['expiration'] if lotes else None),
            'dias_proximo': (lotes[0]['days'] if lotes else None),
        },
    }


def _categorias_compras(sede_ids, ancla, limite=5):
    """Top de categorías contables por monto gastado en el período (datos
    reales de las compras de la Central)."""
    from app.analytics.services import analysis_reports_service as reports_svc
    fin = _sumar_meses(ancla, 1) - timedelta(days=1)
    cons = reports_svc.consolidado_financiero(sede_ids, ancla, fin, 'USD',
                                              incluir_compras=True)
    filas = [f for f in cons.get('por_categoria', []) if f['monto'] > 0]
    filas.sort(key=lambda f: -float(f['monto']))
    return filas[:limite]
