from app.extensions import db
from app.models.security_model import LoginAudit

class AuditRepository:
    @staticmethod
    def guardar_log(user_id, role_id, action, location_id=None):
        """
        Su única función es interactuar con SQLAlchemy para insertar el registro.
        """
        nuevo_log = LoginAudit(
            user_id=user_id,
            role_id=role_id,
            location_id=location_id,
            action=action,
            timestamp=None # 👈 ESTO FORZA A QUE SE EJECUTE EL @validates('timestamp')
        )
        db.session.add(nuevo_log)
        db.session.commit()
        return nuevo_log