from app.models.security_model import User
from app.extensions import db

class UserManagementRepository:
    @staticmethod
    def get_pending_users(sort_order='desc'):
        """Trae usuarios con role_id = 0, ordenados por ID."""
        query = User.query.filter_by(role_id=0)
        
        if sort_order == 'desc':
            return query.order_by(User.id.desc()).all()
        
        return query.order_by(User.id.asc()).all()

    @staticmethod
    def update_user_status(user_id, role_id):
        """Actualiza el rol y activa al usuario."""
        usuario = User.query.get(user_id)
        if usuario:
            usuario.role_id = int(role_id)
            usuario.is_active = True
            db.session.commit()
            return usuario
        return None

    @staticmethod
    def delete_user(user_id):
        """Elimina un usuario rechazado."""
        usuario = User.query.get(user_id)
        if usuario:
            db.session.delete(usuario)
            db.session.commit()
            return True
        return False
    