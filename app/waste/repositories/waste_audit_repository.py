from app.models.waste_model import AuditLog  # Ajusta la ruta a tu modelo
from app.models.security_model import User
from app.models.logistics_model import Location
from app.extensions import db

class WasteAuditRepository:

    @staticmethod
    def get_audit_logs(location_ids=None, start_date=None, end_date=None, severity=None):
        query = db.session.query(AuditLog, User, Location)\
            .outerjoin(User, AuditLog.user_id == User.id)\
            .outerjoin(Location, AuditLog.location_id == Location.id)\
            .filter(AuditLog.action == 'MERMA')

        if location_ids is not None:
            if isinstance(location_ids, list):
                query = query.filter(AuditLog.location_id.in_(location_ids))
            else:
                query = query.filter(AuditLog.location_id == location_ids)

        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        if severity:
            query = query.filter(AuditLog.severity == severity)

        results = query.order_by(AuditLog.timestamp.desc()).all()

        # Unir manualmente los objetos para que el servicio los reciba completos
        logs = []
        for log, user, location in results:
            log.user = user
            log.location = location
            logs.append(log)

        return logs