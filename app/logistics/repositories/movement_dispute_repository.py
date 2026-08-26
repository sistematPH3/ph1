import json
from app.extensions import db
from app.models import Movement, Location, Product, AuditLog

class MovementDisputeRepository:

    @staticmethod
    def get_pending_disputes():
        """
        Retorna todos los traslados que registraron novedades en muelle 
        y aún no han sido arbitrados (resolved_by_id es None).
        """
        # 1. Buscar primero en AuditLog todos los eventos de novedad e incidencia
        audit_logs = AuditLog.query.filter(
            AuditLog.affected_table == 'movements',
            AuditLog.action.in_(['RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD'])
        ).order_by(AuditLog.timestamp.desc()).all()

        notes_map = {}
        status_map = {}
        audit_movement_ids = set()

        for log in audit_logs:
            data = log.changed_data
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}

            if isinstance(data, dict):
                m_id = data.get('movement_id') or data.get('id')
                note = data.get('notes') or data.get('observation')
                nov_type = data.get('novelty_type') or data.get('status')

                if m_id:
                    audit_movement_ids.add(m_id)
                    if note and m_id not in notes_map:
                        notes_map[m_id] = note
                    if nov_type and m_id not in status_map:
                        status_map[m_id] = nov_type

        # 2. Lista de estados tradicionales en BD
        dispute_statuses = [
            'NOVEDAD_FALTANTE', 'FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE',
            'PRODUCTO_ERRONEO', 'SKU_CRUZADO', 'VIOLACION_CUSTODIA',
            'INCIDENCIA_TEMPERATURA', 'VENCIMIENTO_PROXIMO', 'LOTE_NO_COINCIDE',
            'RECHAZO_POR_ESPACIO', 'RETORNO_EMERGENCIA', 'RECIBIDO_CON_NOVEDAD',
            'EN_DISPUTA'
        ]

        # 3. Consulta flexible: Movimientos no resueltos que estén en AuditLog O tengan un estatus de disputa
        query_conditions = [Movement.resolved_by_id.is_(None)]

        if audit_movement_ids:
            query_conditions.append(
                db.or_(
                    Movement.status.in_(dispute_statuses),
                    Movement.id.in_(list(audit_movement_ids))
                )
            )
        else:
            query_conditions.append(Movement.status.in_(dispute_statuses))

        movements = Movement.query.filter(*query_conditions).order_by(Movement.date.desc()).all()

        if not movements:
            return []

        # 4. Mapeo de Sedes y Productos
        locations_map = {loc.id: loc.name for loc in Location.query.all()}
        products_map = {prod.id: prod.name for prod in Product.query.all()} if 'Product' in globals() else {}

        # 5. Enriquecer los objetos Movement
        for mov in movements:
            mov.origin_name = locations_map.get(mov.origin_location_id, f"Sede #{mov.origin_location_id}")
            mov.destination_name = locations_map.get(mov.destination_location_id, f"Sede #{mov.destination_location_id}")

            # Asignar notas obtenidas del AuditLog o los detalles
            detail_note = next((d.notes for d in mov.details if getattr(d, 'notes', None)), None)
            mov.notes = notes_map.get(mov.id) or detail_note or getattr(mov, 'resolution_notes', None)

            # Estado real extraído directamente del AuditLog
            mov.real_status = status_map.get(mov.id) or mov.status

            for detail in mov.details:
                detail.product_name = products_map.get(detail.product_id, f"Producto #{detail.product_id}")

        return movements