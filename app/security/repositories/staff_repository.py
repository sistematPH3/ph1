from app.extensions import db
from app.models.security_model import User, Role 
from app.models.logistics_model import Location 

class StaffRepository:
    @staticmethod
    def get_all_approved_staff():
        return User.query.filter(User.role_id != 0).all()

    @staticmethod
    def get_active_locations():
        return Location.query.filter(Location.is_active == True, Location.id != 1).all()

    @staticmethod
    def get_all_roles():
        return Role.query.filter(Role.id != 0).all()
    
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_locations_by_ids(location_ids):
        """Busca múltiples sedes por su lista de IDs."""
        return Location.query.filter(Location.id.in_(location_ids)).all()

    @staticmethod
    def update_user(user, email, role_id, locations):
        """Actualiza los campos básicos y la relación de sedes."""
        try:
            user.email = email
            user.role_id = role_id
            user.locations = locations # SQLAlchemy gestiona la relación Many-to-Many
            db.session.commit()
            return True, "Usuario actualizado correctamente"
        except Exception as e:
            db.session.rollback()
            error_msg = str(e)
            
            # Detectamos si el error de la base de datos es por correo duplicado
            if 'UniqueViolation' in error_msg or 'users_email_key' in error_msg:
                return False, "El correo electrónico ingresado ya pertenece a otro usuario registrado."
            
            # Si es cualquier otro error raro, evitamos mostrar código al usuario
            return False, "No se pudo actualizar el usuario debido a un error interno del sistema."