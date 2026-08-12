from sqlalchemy import desc
from sqlalchemy.orm import joinedload
from app.models import db, UserAudit, user_locations

class AuditUserRepository:
    @staticmethod
    def get_user_audits(current_user=None):
        # 1. Consulta base con carga optimizada
        query = UserAudit.query.options(
            joinedload(UserAudit.responsible_user),
            joinedload(UserAudit.target_user),
            joinedload(UserAudit.role)
        )

        # 2. Evaluación de permisos para el rol Finanzas
        if current_user:
            user_role_name = current_user.role.name.lower().strip() if (hasattr(current_user, 'role') and current_user.role) else ''
            user_location_ids = [loc.id for loc in current_user.locations] if hasattr(current_user, 'locations') else []

            # Log para verificar en la terminal qué detecta Flask
            print(f"[AUDITORIA USUARIOS] ROL: '{user_role_name}', SEDES DEL USUARIO: {user_location_ids}")

            if user_role_name in ['finance', 'finanzas'] or getattr(current_user, 'is_finance', False):
                if user_location_ids:
                    # Obtenemos directamente de user_locations los IDs de los usuarios de esa sede
                    allowed_user_ids = db.session.query(user_locations.c.user_id)\
                        .filter(user_locations.c.location_id.in_(user_location_ids))

                    # Filtramos las auditorías donde el usuario afectado (target_user_id) esté en esa lista
                    query = query.filter(UserAudit.target_user_id.in_(allowed_user_ids))
                else:
                    # Si Finanzas no tiene sedes asignadas, no muestra ningún registro
                    query = query.filter(db.false())

        # 3. Retorno ordenado por fecha descendente
        return query.order_by(desc(UserAudit.timestamp)).all()

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