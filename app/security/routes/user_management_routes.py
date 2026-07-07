from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from ..repositories.user_management_repository import UserManagementRepository
from ..requests.user_management_validators import UserManagementValidator
from .. import security_bp 
from app.models.logistics_model import Location 

def check_admin_roles():
    """Verifica si el usuario actual tiene permisos de administración."""
    roles_permitidos = ['Administrator', 'Manager', 'Assistant Manager']
    user_role_name = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    if user_role_name not in roles_permitidos:
        abort(403) 

@security_bp.route('/admin/pending-requests')
@login_required
def admin_pending_requests():
    """Muestra la vista de solicitudes de registro pendientes."""
    check_admin_roles() 
    order = request.args.get('sort', 'desc')
    
    # Obtenemos los usuarios en espera y las sedes habilitadas
    usuarios = UserManagementRepository.get_pending_users(sort_order=order)
    sedes = Location.query.filter_by(is_active=True).all()
    
    return render_template('security/pending_requests.html', usuarios_espera=usuarios, sedes=sedes)

@security_bp.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    """Aprueba a un usuario asignándole un rol y sus respectivas sedes laborales."""
    check_admin_roles() 
    
    role_id = request.form.get('role_id')
    # Capturamos la lista de IDs de las sedes desde los checkboxes de la interfaz
    location_ids = request.form.getlist('location_ids')
    
    # Regla de negocio: Solo exigir sedes si el rol seleccionado NO es el de Administrador (ID 1)
    if role_id != '1' and not location_ids:
        flash("Debes seleccionar al menos una sede para este usuario.", "danger")
        return redirect(url_for('security.admin_pending_requests'))
    
    # Validaciones lógicas adicionales del formulario
    if not UserManagementValidator.validate_approval(user_id, role_id):
        return redirect(url_for('security.admin_pending_requests'))
    
    # Procesamos la aprobación a través del repositorio centralizado
    if UserManagementRepository.update_user_status(user_id, role_id, location_ids):
        flash("¡Usuario aprobado, sedes asignadas y activado correctamente!", "success")
    else:
        flash("Error: No se pudo actualizar el estado del usuario.", "danger")
        
    return redirect(url_for('security.admin_pending_requests'))

@security_bp.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_user(user_id):
    """Rechaza una solicitud de registro, eliminando el aspirante de forma segura."""
    check_admin_roles() 
    
    # El repositorio ahora se encarga de limpiar auditorías y tablas intermedias primero
    if UserManagementRepository.delete_user(user_id):
        flash("La solicitud ha sido rechazada y eliminada de la base de datos.", "warning")
    else:
        flash("Error al intentar eliminar el registro. Inténtalo de nuevo.", "danger")
        
    return redirect(url_for('security.admin_pending_requests'))