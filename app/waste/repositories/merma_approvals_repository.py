"""Repositorio de la bandeja de aprobaciones de mermas (solo Admin aprueba/rechaza).

Sigue el patrón Route -> Service -> Repository del proyecto. Aquí SOLO hay
consultas y escrituras a la base; la lógica de negocio (descuento de stock,
notificación y auditoría) vive en merma_approvals_service.py.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import func

from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location
from app.models.security_model import User, user_locations
from app.models.waste_model import Waste, WasteType, WasteDetail, AuditLog, AppParameter


class MermaApprovalsRepository:
    """Acceso a datos para la bandeja de aprobación de mermas pendientes."""

    # ------------------------------------------------------------------
    # Usuarios / sedes
    # ------------------------------------------------------------------
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_all_locations():
        return Location.query.filter(Location.is_active == True).all()  # noqa: E712

    @staticmethod
    def get_user_locations(user_id):
        loc_ids_result = db.session.query(
            user_locations.c.location_id
        ).filter(user_locations.c.user_id == user_id).all()
        loc_ids = [row[0] for row in loc_ids_result]
        if not loc_ids:
            return []
        return Location.query.filter(
            Location.id.in_(loc_ids), Location.is_active == True  # noqa: E712
        ).all()

    @staticmethod
    def get_admins():
        return User.query.filter(User.role.has(name='Administrator')).all()

    # ------------------------------------------------------------------
    # Mermas pendientes (cola de espera / bandeja)
    # ------------------------------------------------------------------
    @staticmethod
    def list_pending(location_ids):
        """Mermas en estado PENDIENTE, opcionalmente filtradas por sedes.

        location_ids: lista de ids de sede permitidos (None => todas).
        """
        q = db.session.query(
            Waste.id,
            Waste.location_id,
            Waste.notes,
            Waste.evidence_url,
            Waste.date,
            Waste.user_id,
            Waste.total_quantity,
            func.coalesce(WasteType.name, 'Sin tipo').label('type_name'),
            func.coalesce(WasteType.code, '').label('type_code'),
            func.coalesce(WasteType.requires_approval, False).label('type_requires_approval'),
            Location.name.label('location_name'),
            func.coalesce(User.name, 'Desconocido').label('author_name'),
        ).join(
            Location, Waste.location_id == Location.id
        ).outerjoin(
            WasteType, Waste.waste_type_id == WasteType.id
        ).outerjoin(
            User, Waste.user_id == User.id
        ).filter(Waste.status == 'PENDIENTE')

        if location_ids:
            q = q.filter(Waste.location_id.in_(location_ids))

        rows = q.order_by(Waste.date.asc()).all()
        return [{
            'id': r.id,
            'location_name': r.location_name,
            'location_id': r.location_id,
            'type_name': r.type_name,
            'type_code': r.type_code,
            'type_requires_approval': bool(r.type_requires_approval),
            'notes': r.notes or '',
            'evidence_url': r.evidence_url,
            'date': r.date,
            'author_name': r.author_name,
            'created_by': r.user_id,
            'total_quantity': float(r.total_quantity or 0),
        } for r in rows]

    # ------------------------------------------------------------------
    # Detalle de una merma (cabecera + líneas)
    # ------------------------------------------------------------------
    @staticmethod
    def get_waste_with_type(waste_id):
        return db.session.query(
            Waste,
            func.coalesce(WasteType.name, 'Sin tipo').label('type_name'),
            func.coalesce(WasteType.code, '').label('type_code'),
            func.coalesce(WasteType.requires_approval, False).label('type_requires_approval'),
            Location.name.label('location_name'),
            func.coalesce(User.name, 'Desconocido').label('author_name'),
        ).join(
            Location, Waste.location_id == Location.id
        ).outerjoin(
            WasteType, Waste.waste_type_id == WasteType.id
        ).outerjoin(
            User, Waste.user_id == User.id
        ).filter(Waste.id == waste_id).first()

    @staticmethod
    def get_details_by_waste(waste_id):
        return WasteDetail.query.filter_by(waste_id=waste_id).all()

    @staticmethod
    def get_product_names(ids):
        if not ids:
            return {}
        prods = Product.query.filter(Product.id.in_(ids)).all()
        return {p.id: p.name for p in prods}

    @staticmethod
    def get_products_info(ids):
        """Nombre + límite de merma (waste_limit) de varios productos a la vez."""
        if not ids:
            return {}
        prods = Product.query.filter(Product.id.in_(ids)).all()
        return {p.id: {
            'name': p.name,
            'waste_limit': float(p.waste_limit) if p.waste_limit is not None else None,
            'unit': p.unit_of_measure or '',
        } for p in prods}

    @staticmethod
    def get_waste_lines(waste_ids):
        """Líneas (producto + cantidad) de varias mermas a la vez: {waste_id: [...]}."""
        if not waste_ids:
            return {}
        rows = WasteDetail.query.filter(WasteDetail.waste_id.in_(waste_ids)).all()
        out = {}
        for d in rows:
            out.setdefault(d.waste_id, []).append({
                'product_id': d.product_id,
                'quantity': float(d.quantity or 0),
            })
        return out

    @staticmethod
    def get_app_parameters():
        """Parámetros configurables del control de mermas (solo reglas de tiempo)."""
        params = AppParameter.query.all()
        return {p.key: p.value for p in params}

    @staticmethod
    def get_merma_history(location_id, since):
        """Mermas (cantidad y fecha) de una sede desde una fecha dada, para la regla de tiempo."""
        rows = Waste.query.filter(
            Waste.location_id == location_id,
            Waste.date >= since,
        ).all()
        return [{'date': r.date, 'total_quantity': float(r.total_quantity or 0)} for r in rows]

    @staticmethod
    def get_last_merma_date(location_id, before_id):
        """Fecha de la merma anterior más reciente de la sede (excluye la merma actual)."""
        last = Waste.query.filter(
            Waste.location_id == location_id,
            Waste.id != before_id,
        ).order_by(Waste.date.desc()).first()
        return last.date if last else None

    @staticmethod
    def get_inventory_item(location_id, product_id):
        return Inventory.query.filter_by(
            location_id=location_id, product_id=product_id
        ).first()

    @staticmethod
    def get_waste_by_id(waste_id):
        return Waste.query.get(waste_id)

    # ------------------------------------------------------------------
    # Escritura: estado y auditoría
    # ------------------------------------------------------------------
    @staticmethod
    def mark_resolved(waste, user_id, new_status):
        """Marca la merma como aprobada o rechazada (el llamado a SET del stock
        lo hace el servicio; aquí solo se actualiza el estado y el aprobador)."""
        waste.status = new_status
        waste.approved_by_id = user_id
        waste.approved_at = datetime.now()

    @staticmethod
    def mark_cancelled(waste, user_id, reason):
        """Autor retira su merma PENDIENTE antes de la respuesta: CANCELADA.

        No toca stock (la merma pendiente nunca lo descontó). El motivo queda
        guardado para la Auditoría de Inventario."""
        waste.status = 'CANCELADA'
        waste.cancelled_by_id = user_id
        waste.cancelled_at = datetime.now()
        waste.cancel_reason = (reason or '').strip()

    @staticmethod
    def create_audit(waste, user_id, event, severity, changed_data):
        payload = dict(changed_data)
        payload.update({
            'event': event,
            'waste_id': waste.id,
            'timestamp': datetime.now().isoformat(),
        })
        db.session.add(AuditLog(
            affected_table='waste',
            action='MERMA',
            severity=severity,
            user_id=user_id,
            location_id=waste.location_id,
            changed_data=json.dumps(payload),
        ))

    @staticmethod
    def commit():
        db.session.commit()

    @staticmethod
    def rollback():
        db.session.rollback()
