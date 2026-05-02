from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from ..repositories.user_management_repository import UserManagementRepository
from ..requests.user_management_validators import UserManagementValidator
from .. import security_bp 


def check_admin_roles():
    
    roles_permitidos = ['Administrator', 'Manager', 'Assistant Manager']
    
   
    
    user_role_name = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    
    if user_role_name not in roles_permitidos:
        abort(403) 

@security_bp.route('/admin/pending-requests')
@login_required
def admin_pending_requests():
    check_admin_roles() 
    order = request.args.get('sort', 'desc')
    
    
    usuarios = UserManagementRepository.get_pending_users(sort_order=order)
    
    return render_template('security/pending_requests.html', usuarios_espera=usuarios)

@security_bp.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    check_admin_roles() 
    role_id = request.form.get('role_id')
    
    if not UserManagementValidator.validate_approval(user_id, role_id):
        return redirect(url_for('security.admin_pending_requests'))
    
    if UserManagementRepository.update_user_status(user_id, role_id):
        flash("¡Usuario aprobado y activado correctamente!", "success")
    else:
        flash("Error: No se pudo encontrar el usuario.", "danger")
        
    return redirect(url_for('security.admin_pending_requests'))

@security_bp.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_user(user_id):
    check_admin_roles() 
    if UserManagementRepository.delete_user(user_id):
        flash("La solicitud ha sido rechazada y eliminada.", "warning")
    else:
        flash("Error al intentar eliminar el registro.", "danger")
        
    return redirect(url_for('security.admin_pending_requests'))