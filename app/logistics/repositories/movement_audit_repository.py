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