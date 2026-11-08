from datetime import date as date_cls, timedelta

from app.extensions import db
from app.models import Movement, MovementDetail, Product, Location
from app.logistics.services.movement_list_service import get_movement_list_context
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard

STATUS_DISPLAY = {
    'EN_TRANSITO':       {'label': 'En Tránsito', 'cls': 'dash-badge-success'},
    'COMPLETADO':        {'label': 'Completado',  'cls': 'dash-badge-info'},
    'CANCELADO_EMISOR':  {'label': 'Cancelado',   'cls': 'dash-badge-danger'},
}


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