# app/logistics/repositories/movement_audit_repository.py
from app.extensions import db
from app.models import AuditLog 

class MovementAuditRepository:
    @staticmethod
    def get_movement_audit_logs(filters):
        query = AuditLog.query.filter_by(affected_table='movements')

        # Filtrado de seguridad para Finanzas
        if 'allowed_locations' in filters:
            query = query.filter(AuditLog.location_id.in_(filters['allowed_locations']))

        if 'location_id' in filters:
            query = query.filter_by(location_id=filters['location_id'])
            
        if 'severity' in filters:
            query = query.filter_by(severity=filters['severity'])
            
        if 'start_date' in filters:
            query = query.filter(AuditLog.timestamp >= filters['start_date'])
            
        if 'end_date' in filters:
            query = query.filter(AuditLog.timestamp <= filters['end_date'])

        return query.order_by(AuditLog.timestamp.desc()).all()

    @staticmethod
    def get_movement_audit_date_range(filters):
        """
        Rango de fechas (min, max) donde existen registros de auditoría de
        traslados. Se respeta la restricción de sedes de Finanzas pero NO los
        filtros de severidad/fechas: el calendario debe ofrecer el rango completo.
        """
        query = AuditLog.query.filter(
            AuditLog.affected_table == 'movements',
            AuditLog.timestamp.isnot(None)
        )

        if 'allowed_locations' in filters:
            query = query.filter(AuditLog.location_id.in_(filters['allowed_locations']))

        min_ts, max_ts = query.with_entities(
            db.func.min(AuditLog.timestamp),
            db.func.max(AuditLog.timestamp)
        ).first()

        return min_ts, max_ts