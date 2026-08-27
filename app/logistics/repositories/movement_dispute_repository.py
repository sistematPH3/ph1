from app.extensions import db
from app.models import Movement, MovementDetail, Location, Product, AuditLog

class MovementDisputeRepository:

    @staticmethod
    def get_pending_disputes():
        dispute_statuses = [
            'NOVEDAD_FALTANTE',
            'RETORNO_EMERGENCIA',
            'RECIBIDO_CON_NOVEDAD',
            'FALTANTE_CONTEO',
            'SOBRANTE_EXCEDENTE',
            'PRODUCTO_ERRONEO',
            'SKU_CRUZADO',
            'VIOLACION_CUSTODIA',
            'INCIDENCIA_TEMPERATURA',
            'VENCIMIENTO_PROXIMO',
            'LOTE_NO_COINCIDE',
            'RECHAZO_POR_ESPACIO',
            'EN_DISPUTA'
        ]

        movements = db.session.query(Movement).filter(
            Movement.resolved_by_id.is_(None),
            Movement.status.in_(dispute_statuses)
        ).order_by(Movement.date.desc()).all()

        if not movements:
            return []

        locations_map = {loc.id: loc.name for loc in db.session.query(Location).all()}
        products_map = {prod.id: prod.name for prod in db.session.query(Product).all()}

        movement_ids = [m.id for m in movements]
        audit_records = db.session.query(AuditLog).filter(
            AuditLog.affected_table == 'movements',
            AuditLog.action.in_(['RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD'])
        ).order_by(AuditLog.timestamp.desc()).all()

        audit_data_map = {}
        for log in audit_records:
            data = log.changed_data if isinstance(log.changed_data, dict) else {}
            m_id = data.get('movement_id')
            if m_id and m_id in movement_ids and m_id not in audit_data_map:
                audit_data_map[m_id] = {
                    'notes': data.get('notes') or data.get('observation') or '',
                    'novelty_type': data.get('novelty_type') or data.get('status') or ''
                }

        for mov in movements:
            mov.origin_name = locations_map.get(mov.origin_location_id, f"Sede #{mov.origin_location_id}")
            mov.destination_name = locations_map.get(mov.destination_location_id, f"Sede #{mov.destination_location_id}")

            logged_info = audit_data_map.get(mov.id, {})
            mov.notes = logged_info.get('notes') or mov.resolution_notes or ''
            mov.real_status = logged_info.get('novelty_type') or mov.status

            for detail in mov.details:
                detail.product_name = products_map.get(detail.product_id, f"Insumo #{detail.product_id}")

        return movements