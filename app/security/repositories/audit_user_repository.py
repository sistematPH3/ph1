from sqlalchemy import desc
from sqlalchemy.orm import joinedload
from app.models import db, UserAudit

class AuditUserRepository:
    @staticmethod
    def get_user_audits():
        return UserAudit.query\
            .options(
                joinedload(UserAudit.responsible_user),
                joinedload(UserAudit.target_user),
                joinedload(UserAudit.role)
            )\
            .order_by(desc(UserAudit.timestamp))\
            .all()

    @staticmethod
    def guardar_auditoria(responsible_user_id, target_user_id, role_id, action, changed_data=None):
        nueva_auditoria = UserAudit(
            responsible_user_id=responsible_user_id,
            target_user_id=target_user_id,
            role_id=role_id,
            action=action,
            changed_data=changed_data,
            timestamp=None
        )
        db.session.add(nueva_auditoria)
        db.session.commit()
        return nueva_auditoria