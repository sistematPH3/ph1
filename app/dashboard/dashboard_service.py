from datetime import date as date_cls, datetime as datetime_cls, time as time_cls, timedelta

from app.extensions import db
from app.models import Movement, MovementDetail, Product, Location
from app.logistics.services.movement_list_service import get_movement_list_context
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard
from app.inventory.services.lot_availability_service import obtener_vencidos_para_dashboard

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
    from app import db
    from app.models import Location, Inventory, Product, Movement, MovementDetail, Waste, WasteDetail
    from datetime import date as date_cls

    # 1. Sedes permitidas del subgerente
    sedes_asignadas = getattr(current_user, 'locations', [])
    if not sedes_asignadas and hasattr(current_user, 'location') and current_user.location:
        sedes_asignadas = [current_user.location]

    allowed_location_ids = [s.id for s in sedes_asignadas if hasattr(s, 'id')]

    if not allowed_location_ids:
        u_loc_id = getattr(current_user, 'location_id', None) or getattr(current_user, 'branch_id', None)
        if u_loc_id:
            allowed_location_ids = [u_loc_id]

    target_location_ids = allowed_location_ids
    location_id = target_location_ids[0] if target_location_ids else None

    # 2. Stock agregado (unidades en inventario)
    stock_agregado = 0
    try:
        if target_location_ids:
            total_qty = db.session.query(db.func.sum(Inventory.current_quantity))\
                .filter(Inventory.location_id.in_(target_location_ids)).scalar()
            stock_agregado = float(total_qty or 0)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error calculando stock subgerente: %s", exc)

    # 3. Consumo en unidades (hoy) – misma lógica que gerencia
    consumo_unidades = 0
    try:
        if target_location_ids:
            inicio_periodo = date_cls.today()  # cambia a .replace(day=1) si quieres del mes

            cant_movs = db.session.query(db.func.sum(MovementDetail.quantity))\
                .join(Movement, MovementDetail.movement_id == Movement.id)\
                .filter(
                    Movement.origin_location_id.in_(target_location_ids),
                    Movement.status == 'COMPLETADO',
                    Movement.date >= inicio_periodo
                )\
                .scalar()

            consumo_unidades = int(cant_movs or 0)

            # Si no hay movimientos, buscar en mermas del periodo
            if consumo_unidades == 0:
                cant_wastes = db.session.query(db.func.sum(WasteDetail.quantity))\
                    .join(Waste, WasteDetail.waste_id == Waste.id)\
                    .filter(
                        Waste.location_id.in_(target_location_ids),
                        Waste.date >= inicio_periodo
                    )\
                    .scalar()
                consumo_unidades = int(cant_wastes or 0)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error calculando consumo unidades subgerente: %s", exc)
        consumo_unidades = 0

    # 4. Lo que ya tenías
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

        # ← NUEVO: lo que necesita la tarjeta de unidades
        'total_stock': int(stock_agregado),
        'consumo_hoy_monto': int(consumo_unidades),
    }

def get_manager_context(current_user, location_id=None):
    """
    Contexto dinámico completo para el Dashboard de Sede.
    Garantiza el conteo real de consumos en unidades.
    """
    from app import db
    from app.models import Location, Inventory, Product, Movement, MovementDetail, Waste, WasteDetail

    g = globals()

    # 1. IDENTIFICACIÓN Y FILTRADO DE SEDES DINÁMICAS
    sedes_asignadas = getattr(current_user, 'locations', [])
    if not sedes_asignadas and hasattr(current_user, 'location') and current_user.location:
        sedes_asignadas = [current_user.location]

    allowed_location_ids = [s.id for s in sedes_asignadas if hasattr(s, 'id')]
    
    if not allowed_location_ids:
        u_loc_id = getattr(current_user, 'location_id', None) or getattr(current_user, 'branch_id', None)
        if u_loc_id:
            allowed_location_ids = [u_loc_id]

    if location_id and location_id in allowed_location_ids:
        target_location_ids = [location_id]
    else:
        target_location_ids = allowed_location_ids
        location_id = target_location_ids[0] if target_location_ids else None

    # Sede actual para mostrar en el Header
    sede_actual = None
    if target_location_ids:
        sede_actual = Location.query.get(target_location_ids[0]) if hasattr(Location, 'query') else None

    # 2. CÁLCULO DE STOCK AGREGADO
    stock_agregado = 0
    ultimo_ingreso = None
    historial_ingresos = []

    try:
        if target_location_ids:
            total_qty = db.session.query(db.func.sum(Inventory.current_quantity))\
                .filter(Inventory.location_id.in_(target_location_ids)).scalar()
            stock_agregado = float(total_qty or 0)

            mov_query = db.session.query(MovementDetail, Product, Location, Movement.date)\
                .join(Movement, MovementDetail.movement_id == Movement.id)\
                .join(Product, MovementDetail.product_id == Product.id)\
                .join(Location, Movement.destination_location_id == Location.id)\
                .filter(
                    Movement.status == 'COMPLETADO',
                    Movement.destination_location_id.in_(target_location_ids)
                )\
                .order_by(Movement.date.desc())\
                .limit(5).all()

            for det, prod, loc, fecha in mov_query:
                unidad = prod.unit_of_measure or 'uds.'
                item = {
                    'producto': prod.name,
                    'cantidad': float(det.quantity or 0),
                    'unidad': unidad,
                    'sede': loc.name,
                    'fecha': fecha.strftime('%d/%m/%Y') if fecha else 'Reciente'
                }
                historial_ingresos.append(item)

            if historial_ingresos:
                ultimo_ingreso = historial_ingresos[0]
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error calculando ingresos stock: %s", exc)

    # 3. TRASLADOS EN TRÁNSITO / POR RECIBIR
    traslados_en_transito = 0
    try:
        if 'get_movement_list_context' in g and callable(g['get_movement_list_context']):
            movs = g['get_movement_list_context'](current_user)
            en_camino = movs.get('en_camino', []) if isinstance(movs, dict) else []
            por_recibir = movs.get('por_recibir', []) if isinstance(movs, dict) else []
            traslados_en_transito = len(en_camino) + len(por_recibir)
            
            if traslados_en_transito == 0 and location_id:
                for m in (en_camino + por_recibir):
                    m_dest = m.get('destination_location_id') if isinstance(m, dict) else getattr(m, 'destination_location_id', None)
                    m_orig = m.get('origin_location_id') if isinstance(m, dict) else getattr(m, 'origin_location_id', None)
                    if m_dest == location_id or m_orig == location_id:
                        traslados_en_transito += 1
    except Exception:
        traslados_en_transito = 0

  # 4. ALERTAS DE STOCK Y VENCIDOS
    alarmas_stock = []
    vencidos = []
    expiring_lots = []

    try:
        if 'obtener_alarmas_para_dashboard' in g and callable(g['obtener_alarmas_para_dashboard']):
            alarmas_stock = g['obtener_alarmas_para_dashboard']()
        if 'obtener_vencidos_para_dashboard' in g and callable(g['obtener_vencidos_para_dashboard']):
            vencidos = g['obtener_vencidos_para_dashboard'](current_user)

        # 1. Obtener lotes sin procesar
        raw_expiring = get_expiring_lots(current_user)
        
        # 2. Mapear y adaptar la estructura a lo que requiere la plantilla
        mapped_lots = []
        for item in raw_expiring:
            expiration_val = item.get('expiration')
            exp_date_str = expiration_val.strftime('%Y-%m-%d') if hasattr(expiration_val, 'strftime') else expiration_val
            
            mapped_lots.append({
                'name': item.get('product'),
                'product': item.get('product'),
                'lot': item.get('lot'),
                'location': item.get('location'),
                'expiration_date': exp_date_str,
                'expiration': expiration_val,
                'quantity': item.get('quantity'),
                'days': item.get('days'),
                'critical': item.get('critical'),
                'location_id': item.get('location_id')
            })

        # 3. Filtrar de forma segura por sede si aplica (sin colisión de variables ni getattr)
        if location_id:
            target_id = location_id
            filtered_lots = []
            for lot_item in mapped_lots:
                item_loc_id = lot_item.get('location_id') if isinstance(lot_item, dict) else None
                if item_loc_id is None or item_loc_id == target_id:
                    filtered_lots.append(lot_item)
            expiring_lots = filtered_lots
        else:
            expiring_lots = mapped_lots

        if location_id:
            alarmas_stock = [
                a for a in alarmas_stock 
                if (isinstance(a, dict) and a.get('location_id') == location_id) or 
                   (hasattr(a, 'location_id') and getattr(a, 'location_id') == location_id)
            ]
            vencidos = [
                v for v in vencidos 
                if (isinstance(v, dict) and (v.get('location_id') == location_id or v.get('location') == location_id)) or
                   (hasattr(v, 'location_id') and getattr(v, 'location_id') == location_id)
            ]
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error procesando alertas y lotes: %s", exc)

    # 5. MERMAS PENDIENTES
    mermas_graves = []
    mermas_pendientes_count = 0
    try:
        query = db.session.query(Waste).filter(Waste.status.in_(['PENDIENTE', 'pending']))
        if target_location_ids:
            query = query.filter(Waste.location_id.in_(target_location_ids))

        mermas_pendientes_count = query.count()
        mermas_graves = query.order_by(
            Waste.date.desc() if hasattr(Waste, 'date') else Waste.id.desc()
        ).limit(5).all()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error obteniendo mermas pendientes: %s", exc)
        mermas_pendientes_count = 0

   # 6. CONSUMO COCINA EN UNIDADES (desde AuditLog - GASTO_COCINA)
    consumo_unidades = 0
    try:
        if target_location_ids:
            from datetime import date as date_cls
            from app.models.waste_model import AuditLog
            import json
            from sqlalchemy import func

            inicio_periodo = date_cls.today()

            audits = db.session.query(AuditLog.changed_data).filter(
                AuditLog.location_id.in_(target_location_ids),
                AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
                func.date(AuditLog.timestamp) >= inicio_periodo
            ).all()

            total = 0.0
            for row in audits:
                c_data = row[0] if row else None
                if not c_data:
                    continue
                if isinstance(c_data, str):
                    try:
                        c_data = json.loads(c_data)
                    except Exception:
                        continue
                if isinstance(c_data, dict):
                    try:
                        qty = float(c_data.get('quantity_changed', 0) or 0)
                        total += abs(qty)
                    except (TypeError, ValueError):
                        continue

            consumo_unidades = int(total)

    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error calculando consumo cocina: %s", exc)
        consumo_unidades = 0

    # 7. RETORNO UNIFICADO
    return {
        'sede': sede_actual,
        'sede_nombre': getattr(sede_actual, 'name', 'Mi Sede') if sede_actual else 'Mi Sede',
        'location': sede_actual,
        'sedes': sedes_asignadas,
        'sede_seleccionada': location_id,
        'alarmas': alarmas_stock,
        'critical_stock_items': alarmas_stock,
        'vencidos': vencidos,
        'expiring_lots': expiring_lots,
        'mermas_graves': mermas_graves,
        'total_stock': int(stock_agregado),
        'consumo_hoy_monto': int(consumo_unidades),
        'pending_wastes_count': int(mermas_pendientes_count),
        'transfers_in_transit_count': int(traslados_en_transito),
        'recent_movements': get_recent_movements(current_user, limit=5),
        'resumen': {
            'stock_agregado': stock_agregado,
            'ultimo_ingreso': ultimo_ingreso,
            'historial_ingresos': historial_ingresos,
            'traslados_en_transito': traslados_en_transito,
            'mermas_pendientes': mermas_pendientes_count,
            'alertas_criticas': len(alarmas_stock) + len(vencidos),
            'cant_stock_bajo': len(alarmas_stock),
            'cant_vencidos': len(vencidos)
        }
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

def get_management_context(current_user, location_id=None):
    """
    Resumen ejecutivo y Panel de AlertasCríticos para Director .
    """
    from app.models import Location, Inventory, Product, Movement, MovementDetail, Waste, WasteDetail

    
    sedes_asignadas = getattr(current_user, 'locations', [])
    allowed_location_ids = [s.id for s in sedes_asignadas]

    if location_id and location_id in allowed_location_ids:
        target_location_ids = [location_id]
    else:
        target_location_ids = allowed_location_ids
        location_id = None


    stock_agregado = 0
    ultimo_ingreso = None
    historial_ingresos = []

    try:
        if target_location_ids:
            
            total_qty = db.session.query(db.func.sum(Inventory.current_quantity))\
                .filter(Inventory.location_id.in_(target_location_ids)).scalar()
            stock_agregado = float(total_qty or 0)

            
            mov_query = db.session.query(MovementDetail, Product, Location, Movement.date)\
                .join(Movement, MovementDetail.movement_id == Movement.id)\
                .join(Product, MovementDetail.product_id == Product.id)\
                .join(Location, Movement.destination_location_id == Location.id)\
                .filter(
                    Movement.status == 'COMPLETADO',
                    Movement.destination_location_id.in_(target_location_ids)
                )\
                .order_by(Movement.date.desc())\
                .limit(5).all()

            for det, prod, loc, fecha in mov_query:
                unidad = prod.unit_of_measure or 'uds.'
                item = {
                    'producto': prod.name,
                    'cantidad': float(det.quantity or 0),
                    'unidad': unidad,
                    'sede': loc.name,
                    'fecha': fecha.strftime('%d/%m/%Y') if fecha else 'Reciente'
                }
                historial_ingresos.append(item)

            if historial_ingresos:
                ultimo_ingreso = historial_ingresos[0]
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error calculando ingresos stock: %s", exc)

    
    traslados_en_transito = 0
    try:
        movs = get_movement_list_context(current_user)
        en_camino = movs.get('en_camino', []) if isinstance(movs, dict) else []
        por_recibir = movs.get('por_recibir', []) if isinstance(movs, dict) else []
        
        if location_id:
            en_camino = [m for m in en_camino if m.get('destination_location_id') == location_id or m.get('origin_location_id') == location_id]
            por_recibir = [m for m in por_recibir if m.get('destination_location_id') == location_id or m.get('origin_location_id') == location_id]
            
        traslados_en_transito = len(en_camino) + len(por_recibir)
    except Exception:
        traslados_en_transito = 0

    
    alarmas_stock = obtener_alarmas_para_dashboard()
    vencidos = obtener_vencidos_para_dashboard(current_user)
    
    if location_id:
        alarmas_stock = [
            a for a in alarmas_stock 
            if (isinstance(a, dict) and a.get('location_id') == location_id) or 
               (hasattr(a, 'location_id') and getattr(a, 'location_id') == location_id)
        ]
        vencidos = [
            v for v in vencidos 
            if (isinstance(v, dict) and (v.get('location_id') == location_id or v.get('location') == location_id)) or
               (hasattr(v, 'location_id') and getattr(v, 'location_id') == location_id)
        ]

    
    mermas_graves = []
    mermas_pendientes_count = 0
    try:
        from app.models import Waste

        
        query = db.session.query(Waste).filter(Waste.status == 'PENDIENTE')
        
        if target_location_ids:
            query = query.filter(Waste.location_id.in_(target_location_ids))

        mermas_pendientes_count = query.count()
        
        
        mermas_graves = query.order_by(
            Waste.date.desc() if hasattr(Waste, 'date') else Waste.id.desc()
        ).limit(5).all()

    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error obteniendo mermas pendientes: %s", exc, exc_info=True)
        mermas_pendientes_count = 0

    alertas_criticas_count = len(alarmas_stock) + len(vencidos)

    
    proximos_vencimientos = get_expiring_lots(
        current_user,
        limit=5,
        horizon_days=7,
    )

    return {
        'sedes': sedes_asignadas,
        'sede_seleccionada': location_id,
        'alarmas': alarmas_stock,
        'vencidos': vencidos,
        'mermas_graves': mermas_graves,
        'proximos_vencimientos': proximos_vencimientos,  
        'resumen': {
            'stock_agregado': stock_agregado,
            'ultimo_ingreso': ultimo_ingreso,
            'historial_ingresos': historial_ingresos,
            'traslados_en_transito': traslados_en_transito,
            'mermas_pendientes': mermas_pendientes_count,
            'alertas_criticas': alertas_criticas_count,
            'cant_stock_bajo': len(alarmas_stock),
            'cant_vencidos': len(vencidos)
        },
        'pendientes': {
            'mermas_pendientes': mermas_pendientes_count,
            'traslados_en_transito': traslados_en_transito
        }
    }

def get_operations_context(current_user, location_id=None):
    from app.models import Movement, Location
    from app.logistics.repositories.movement_dispute_repository import MovementDisputeRepository

    sedes_asignadas = getattr(current_user, 'locations', [])
    allowed_location_ids = [s.id for s in sedes_asignadas]

    if location_id and location_id in allowed_location_ids:
        target_location_ids = [location_id]
    else:
        target_location_ids = allowed_location_ids
        location_id = None

    # Map de nombres de sedes para despliegue
    loc_map = {loc.id: loc.name for loc in Location.query.all()} if target_location_ids else {}

    # 1. TRASLADOS EN TRÁNSITO GENERALES (Origen o Destino en mis sedes)
    query_base = Movement.query
    if target_location_ids:
        query_base = query_base.filter(
            (Movement.origin_location_id.in_(target_location_ids)) | 
            (Movement.destination_location_id.in_(target_location_ids))
        )

    movimientos_en_transito = query_base.filter(Movement.status == 'EN_TRANSITO').all()

    # 2. CONTEO DE TRASLADOS RECIBIDOS (COMPLETADOS EN DESTINO)
    query_recibidos = Movement.query.filter(Movement.status == 'COMPLETADO')
    if target_location_ids:
        query_recibidos = query_recibidos.filter(
            Movement.destination_location_id.in_(target_location_ids)
        )
    traslados_recibidos_count = query_recibidos.count()

    # 2. RECEPCIONES PENDIENTES EN MI SEDE (Movimientos EN_TRANSITO donde mi sede es DESTINO)
    recepciones_pendientes = []
    if target_location_ids:
        query_entrantes = Movement.query.filter(
            Movement.status == 'EN_TRANSITO',
            Movement.destination_location_id.in_(target_location_ids)
        ).order_by(Movement.date.desc()).all()

        for m in query_entrantes:
            recepciones_pendientes.append({
                'id': m.id,
                'origen': loc_map.get(m.origin_location_id, f'Sede #{m.origin_location_id}'),
                'destino': loc_map.get(m.destination_location_id, f'Sede #{m.destination_location_id}'),
                'fecha': m.date.strftime('%d/%m/%Y %H:%M') if m.date else 'N/A',
                'tipo': str(getattr(m, 'movement_type', getattr(m, 'type', 'TRASLADO'))).upper()
            })

    # 3. ALERTAS DE STOCK Y VENCIDOS
    alarmas_stock = obtener_alarmas_para_dashboard()
    vencidos = obtener_vencidos_para_dashboard(current_user)

    if location_id:
        alarmas_stock = [
            a for a in alarmas_stock 
            if (isinstance(a, dict) and a.get('location_id') == location_id) or 
               (hasattr(a, 'location_id') and getattr(a, 'location_id') == location_id)
        ]
        vencidos = [
            v for v in vencidos 
            if (isinstance(v, dict) and (v.get('location_id') == location_id or v.get('location') == location_id)) or
               (hasattr(v, 'location_id') and getattr(v, 'location_id') == location_id)
        ]

    # 4. DISPUTAS E INCIDENCIAS (Usando repositorio oficial)
    query_disputas = Movement.query.filter(
        Movement.status.in_(MovementDisputeRepository.PENDING_DISPUTE_STATUSES)
    )

    if target_location_ids:
        query_disputas = query_disputas.filter(
            (Movement.origin_location_id.in_(target_location_ids)) | 
            (Movement.destination_location_id.in_(target_location_ids))
        )

    disputas_pendientes = query_disputas.all()

    return {
        'sedes': sedes_asignadas,
        'sede_seleccionada': location_id,
        'resumen': {
            'en_transito_count': len(movimientos_en_transito),
            'recibidos_count': traslados_recibidos_count,
            'disputas_count': len(disputas_pendientes),
            'mermas_count': len(vencidos),
            'cant_recepciones_pendientes': len(recepciones_pendientes)
        },
        'recepciones_pendientes': recepciones_pendientes[:5],
        'disputas_pendientes': disputas_pendientes[:5],
        'alarmas_stock': alarmas_stock[:5],
        'vencidos': vencidos[:5]
    }