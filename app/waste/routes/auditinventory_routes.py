from flask import Blueprint, render_template, request, jsonify, abort, session
from flask_login import login_required, current_user
# Importamos la función de servicio que obtiene las sedes
from app.waste.services.auditinventory_service import get_audit_view_data, fetch_filtered_audit_logs

auditinventory_bp = Blueprint('auditinventory_bp', __name__)

@auditinventory_bp.route('/waste/audit', methods=['GET'])
@login_required
def view_audit_page():
    # Obtenemos el role_id directamente
    role_id = getattr(current_user, 'role_id', None) or session.get('role_id')

    # Rol 4 (Operations) no tiene permisos para este módulo
    if role_id == 4:
        abort(403, description="No tienes permisos para acceder al módulo de auditoría.")

    # Solo el Rol 1 (Administrator) es admin total
    is_admin = (role_id == 1)
    user_location_id = getattr(current_user, 'location_id', None) or session.get('location_id')

    # OBTENER LAS SEDES DESDE EL SERVICIO
    locations, is_admin_status, user = get_audit_view_data(current_user.id)

    return render_template(
        'waste/auditinventory.html', 
        is_admin=is_admin, 
        user_location_id=user_location_id,
        locations=locations  # <-- Pasamos las sedes al HTML
    )

@auditinventory_bp.route('/api/waste/audit', methods=['GET'])
@login_required
def get_audit_api():
    role_id = getattr(current_user, 'role_id', None) or session.get('role_id')

    # Rol 4 (Operations) no tiene permisos
    if role_id == 4:
        return jsonify({'success': False, 'message': 'Acceso no autorizado'}), 403

    is_admin = (role_id == 1)
    
    location_id = request.args.get('location_id')
    severity = request.args.get('severity')

    filters = {
        'location_id': location_id,
        'severity': severity
    }
    
    # Pasamos el usuario, is_admin y los filtros al servicio
    logs = fetch_filtered_audit_logs(user=current_user, is_admin=is_admin, filters=filters)

    return jsonify({'success': True, 'logs': logs})