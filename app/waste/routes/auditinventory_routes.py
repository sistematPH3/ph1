from flask import Blueprint, render_template, request, jsonify, abort, session
from flask_login import login_required, current_user
from app.waste.services.auditinventory_service import get_audit_view_data, fetch_filtered_audit_logs, process_inventory_action
from app.waste.requests.auditinventory_validators import validate_audit_action

auditinventory_bp = Blueprint('auditinventory_bp', __name__)

@auditinventory_bp.route('/waste/audit', methods=['GET'])
@login_required
def view_audit_page():
    role_id = getattr(current_user, 'role_id', None) or session.get('role_id')

    # Si tuvieras algún rol completamente restringido (ej. Guest=0), se validaría aquí.
    # Operaciones (4), Finanzas (6), Gerente (2), Sub Gerente (3) y Directores (5) pueden acceder.

    is_admin = (role_id == 1)
    user_location_id = getattr(current_user, 'location_id', None) or session.get('location_id')

    locations, is_admin_status, user = get_audit_view_data(current_user.id)

    return render_template(
        'waste/auditinventory.html', 
        is_admin=is_admin, 
        user_location_id=user_location_id,
        locations=locations  
    )

@auditinventory_bp.route('/api/waste/audit', methods=['GET'])
@login_required
def get_audit_api():
    role_id = getattr(current_user, 'role_id', None) or session.get('role_id')
    user_location_id = getattr(current_user, 'location_id', None) or session.get('location_id')

    is_admin = (role_id == 1)
    
    # Si es Administrador puede filtrar la sede que desee.
    # Para los demás roles (Operaciones, Finanzas, Gerente, Sub Gerente, Directores) se fuerza su sede asignada.
    if is_admin:
        location_id = request.args.get('location_id')
    else:
        location_id = user_location_id

    severity = request.args.get('severity')

    filters = {
        'location_id': location_id,
        'severity': severity
    }
    
    logs = fetch_filtered_audit_logs(user=current_user, is_admin=is_admin, filters=filters)

    return jsonify({'success': True, 'logs': logs})

@auditinventory_bp.route('/api/waste/audit/action', methods=['POST'])
@login_required
def execute_audit_action():
    role_id = getattr(current_user, 'role_id', None) or session.get('role_id')
    
    # Bloqueo explícito de escritura para Operaciones (4) y Finanzas (6)
    if role_id in [4, 6]:
        return jsonify({'success': False, 'message': 'Operación denegada. Su perfil no tiene permisos de escritura en este módulo.'}), 403

    data = request.get_json()
    
    validation = validate_audit_action(data)
    if not validation['is_valid']:
        return jsonify({'success': False, 'message': 'Datos inválidos', 'errors': validation['errors']}), 400

    log_id = data.get('log_id')
    action_type = data.get('action_type')
    notes = data.get('notes')
    new_quantity = data.get('new_quantity')
    
    result = process_inventory_action(
        log_id=log_id, 
        current_user=current_user, 
        action_type=action_type, 
        new_quantity_requested=new_quantity, 
        justification_notes=notes
    )
    
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code