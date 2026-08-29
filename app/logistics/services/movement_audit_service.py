# app/logistics/services/movement_audit_service.py
from app.extensions import db
# IMPORTANTE: Asegúrate de importar User y Location desde tus modelos
from app.models import AuditLog, User, Location 
from app.logistics.repositories.movement_audit_repository import MovementAuditRepository

class MovementAuditService:
    @staticmethod
    def log_movement_event(action, severity, user_id, location_id, changed_data):
        """
        Método centralizado log_movement_event para persistir los contratos JSONB inmutables generados por los submódulos 1, 2 y 3.
        """
        audit_entry = AuditLog(
            affected_table='movements',
            action=action, 
            severity=severity, 
            user_id=user_id,
            location_id=location_id,
            changed_data=changed_data 
        )
        db.session.add(audit_entry)
        db.session.commit()
        return True

    @staticmethod
    def get_structured_audits(filters):
        """
        Estructuración de datos para el visor de auditoría.
        """
        logs = MovementAuditRepository.get_movement_audit_logs(filters)
        
        # SOLUCIÓN: Hidratación dinámica sin tocar el modelado.
        # Adjuntamos las instancias manualmente para satisfacer a la vista Jinja.
        for log in logs:
            log.user = User.query.get(log.user_id) if log.user_id else None
            log.location = Location.query.get(log.location_id) if log.location_id else None
            
        return logs