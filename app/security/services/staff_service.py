from app.security.repositories.staff_repository import StaffRepository
from app.extensions import db
from flask_login import current_user
from app.security.services.audit_user_service import AuditUserService

class StaffService:
    @staticmethod
    def get_staff_list_data():
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
        usuario = StaffRepository.get_user_by_id(user_id)
        
        if not usuario:
            return False, "Usuario no encontrado."
            
        # REGLA AÑADIDA: Evitar que el usuario en sesión se desactive a sí mismo
        if usuario.id == current_user.id and nuevo_estado is False:
            return False, "Acción denegada: No puedes desactivar tu propia cuenta."
        
        estado_anterior = usuario.is_active
        
        if nuevo_estado:
            es_admin = usuario.is_admin 
            sedes_activas = [loc for loc in usuario.locations if loc.is_active]
            
            if not es_admin and len(sedes_activas) == 0:
                return False, "Error: El personal debe tener al menos una sede ACTIVA asignada para activarse."
        
        usuario.is_active = nuevo_estado
        db.session.commit()
        
        if estado_anterior != nuevo_estado:
            AuditUserService.registrar_modificacion(
                responsible_user_id=current_user.id,
                target_user_id=usuario.id,
                role_id=current_user.role_id,
                action='ACTIVATE' if nuevo_estado else 'DEACTIVATE',
                changed_data={
                    'estado': {
                        'old': 'Activo' if estado_anterior else 'Inactivo', 
                        'new': 'Activo' if nuevo_estado else 'Inactivo'
                    }
                }
            )
            
        return True, "Estado actualizado correctamente."

    @staticmethod
    def actualizar_usuario(user_id, data):
        usuario = StaffRepository.get_user_by_id(user_id)
        if not usuario:
            return False, "Usuario no encontrado."

        estado_anterior = {
            'email': usuario.email,
            'rol': usuario.role.name if usuario.role else 'Ninguno',
            'sedes': ', '.join([loc.name for loc in usuario.locations if loc.is_active]) or 'Ninguna'
        }

        nuevo_email = data.get('email')

        # REGLA: Si el administrador se está editando a sí mismo, 
        # conservamos su rol y sedes actuales (ignoramos lo que venga del formulario).
        if usuario.id == current_user.id:
            nuevo_rol_id = usuario.role_id
            nuevas_sedes = usuario.locations
        else:
            # Si está editando a OTRA persona, procesamos los roles y sedes normalmente
            location_ids = data.get('locations', [])
            nuevas_sedes = StaffRepository.get_locations_by_ids(location_ids)
            nuevo_rol_id = int(data.get('role_id'))

        exito, mensaje = StaffRepository.update_user(
            user=usuario,
            email=nuevo_email,
            role_id=nuevo_rol_id,
            locations=nuevas_sedes
        )

        if exito:
            estado_nuevo = {
                'email': usuario.email,
                'rol': usuario.role.name if usuario.role else 'Ninguno',
                'sedes': ', '.join([loc.name for loc in usuario.locations if loc.is_active]) or 'Ninguna'
            }

            cambios = {}
            for campo in ['email', 'rol', 'sedes']:
                if estado_anterior[campo] != estado_nuevo[campo]:
                    cambios[campo] = {
                        'old': estado_anterior[campo], 
                        'new': estado_nuevo[campo]
                    }

            if cambios:
                AuditUserService.registrar_modificacion(
                    responsible_user_id=current_user.id,
                    target_user_id=usuario.id,
                    role_id=current_user.role_id,
                    action='UPDATE',
                    changed_data=cambios
                )

        return exito, mensaje

    @staticmethod
    def activar_personal_por_sede(location_id):
        try:
            staff = StaffRepository.get_all_approved_staff()
            usuarios_activados = 0

            for usuario in staff:
                if usuario.is_active:
                    continue
                
                pertenece_a_sede = any(loc.id == location_id for loc in usuario.locations)
                
                if pertenece_a_sede:
                    usuario.is_active = True
                    usuarios_activados += 1
                    
                    AuditUserService.registrar_modificacion(
                        responsible_user_id=current_user.id,
                        target_user_id=usuario.id,
                        role_id=current_user.role_id,
                        action='ACTIVATE',
                        changed_data={
                            'estado': {
                                'old': 'Inactivo', 
                                'new': 'Activo'
                            }
                        }
                    )

            if usuarios_activados > 0:
                db.session.commit()
                return True, f"Se activaron correctamente {usuarios_activados} usuarios asociados a la sede."
            
            return True, "No se encontraron usuarios inactivos en esta sede."

        except Exception as e:
            db.session.rollback()
            return False, f"Error al procesar la activación masiva: {str(e)}"