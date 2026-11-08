from app.models.security_model import User
from app.models.logistics_model import Location
from app.extensions import db
from app.models import LoginAudit

class UserManagementRepository:
    @staticmethod
    def get_pending_users(sort_order='desc'):
        """Trae usuarios con role_id = 0, ordenados por ID."""
        query = User.query.filter_by(role_id=0)
        
        if sort_order == 'desc':
            return query.order_by(User.id.desc()).all()
        
        return query.order_by(User.id.asc()).all()

    @staticmethod
    def update_user_status(user_id, role_id, location_ids):
        """Actualiza el rol, asigna sedes (vía user_locations) y activa al usuario mediante sincronización."""
        usuario = User.query.get(user_id)
        if usuario:
            usuario.role_id = int(role_id)
            
            # Buscamos las sedes según los IDs recibidos
            selected_locations = Location.query.filter(Location.id.in_(location_ids)).all()
            
            # Asignamos la relación (SQLAlchemy maneja la tabla user_locations automáticamente)
            usuario.locations = selected_locations
            
            # Ejecutamos tu función centralizada para definir si se activa o inhabilita
            usuario.sync_activation_status() 
            
            db.session.commit()
            return usuario
        return None

    @staticmethod
    def delete_user(user_id):
        """
        Elimina un usuario de la base de datos de forma segura al ser rechazado.
        Limpia el historial de LoginAudit y desvincula las sedes asignadas temporalmente 
        para prevenir errores de restricción de clave foránea (IntegrityError).
        """
        try:
            usuario = User.query.get(user_id)
            if usuario:
                # 1. Eliminamos los registros de auditoría vinculados al usuario guest
                LoginAudit.query.filter_by(user_id=user_id).delete()
                
                # 2. Vaciamos la relación de sedes para limpiar la tabla intermedia 'user_locations'
                usuario.locations = []
                
                # 3. Borramos al usuario de la tabla 'users'
                db.session.delete(usuario)
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            # Imprime el error en la consola de Flask por si necesitas depurar algo más
            print(f"Error detectado al eliminar usuario rechazado: {e}")
            return False