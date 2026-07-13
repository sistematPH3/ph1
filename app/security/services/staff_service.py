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

    @staticmethod
    def activar_personal_por_sede(location_id):
        """
        Busca y activa masivamente a todos los miembros del personal 
        que estén INACTIVOS y pertenezcan a la sede especificada.
        """
        try:
            # Reutilizamos el método del repositorio para traer el personal
            staff = StaffRepository.get_all_approved_staff()
            usuarios_activados = 0

            for usuario in staff:
                # Si el usuario ya está activo, lo ignoramos para ahorrar procesamiento
                if usuario.is_active:
                    continue
                
                # Comprobamos si el usuario tiene vinculada la sede que estamos activando
                pertenece_a_sede = any(loc.id == location_id for loc in usuario.locations)
                
                if pertenece_a_sede:
                    usuario.is_active = True
                    usuarios_activados += 1

            # Solo hacemos commit si realmente hubo cambios que guardar
            if usuarios_activados > 0:
                db.session.commit()
                return True, f"Se activaron correctamente {usuarios_activados} usuarios asociados a la sede."
            
            return True, "No se encontraron usuarios inactivos en esta sede."

        except Exception as e:
            db.session.rollback()
            return False, f"Error al procesar la activación masiva: {str(e)}"