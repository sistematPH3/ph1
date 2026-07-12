from app.security.repositories.staff_repository import StaffRepository
from app.extensions import db

class StaffService:
    @staticmethod
    def get_staff_list_data():
        """Retorna la data necesaria para renderizar el listado del personal."""
        staff = StaffRepository.get_all_approved_staff()
        roles = StaffRepository.get_all_roles()
        locations = StaffRepository.get_active_locations()
        
        return {
            'staff': staff,
            'roles': roles,
            'locations': locations
        }

    @staticmethod
    def actualizar_estado(user_id, nuevo_estado):
        """Gestiona la activación/desactivación validando la existencia de sedes ACTIVAS."""
        usuario = StaffRepository.get_user_by_id(user_id)
        
        if not usuario:
            return False, "Usuario no encontrado."
        
        # Si se intenta activar el usuario, validamos las sedes
        if nuevo_estado:
            # Usamos la propiedad lógica del modelo (es_admin) y filtramos sedes activas
            es_admin = usuario.is_admin 
            sedes_activas = [loc for loc in usuario.locations if loc.is_active]
            
            # El usuario no es admin y no tiene ninguna sede activa asociada
            if not es_admin and len(sedes_activas) == 0:
                return False, "Error: El personal debe tener al menos una sede ACTIVA asignada para activarse."
        
        usuario.is_active = nuevo_estado
        db.session.commit()
        return True, "Estado actualizado correctamente."

    @staticmethod
    def actualizar_usuario(user_id, data):
        """Actualiza la información del usuario y sus sedes asociadas."""
        usuario = StaffRepository.get_user_by_id(user_id)
        if not usuario:
            return False, "Usuario no encontrado."

        # 1. Obtener los objetos de sedes basados en los IDs enviados
        location_ids = data.get('locations', [])
        nuevas_sedes = StaffRepository.get_locations_by_ids(location_ids)

        # 2. Persistir cambios usando el repositorio
        return StaffRepository.update_user(
            user=usuario,
            email=data.get('email'),
            role_id=data.get('role_id'),
            locations=nuevas_sedes
        )