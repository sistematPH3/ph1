from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.waste.services.waste_config_service import WasteConfigService
from app.waste.requests.waste_config_validators import WasteConfigValidators

waste_config_bp = Blueprint('waste_config', __name__, template_folder='../templates')


@waste_config_bp.route('/waste/merma/config', methods=['GET'])
@login_required
def configuracion():
    # Validar si es admin usando la propiedad is_admin o el nombre de rol
    is_admin_user = getattr(current_user, 'is_admin', False) or getattr(current_user, 'role', None) == 'Administrator'
    
    if not is_admin_user:
        flash('Acceso no autorizado.', 'danger')
        return redirect('/')

    user_role_id = getattr(current_user, 'role_id', 1)
    configs = WasteConfigService.get_config_data(current_user_role_id=user_role_id)
    return render_template('waste/waste_config.html', configs=configs)


@waste_config_bp.route('/api/waste/merma/config', methods=['POST'])
@login_required
def guardar_config():
    is_admin_user = getattr(current_user, 'is_admin', False) or getattr(current_user, 'role', None) == 'Administrator'
    
    if not is_admin_user:
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    data = request.form.to_dict() if request.form else (request.get_json() or {})
    errors = WasteConfigValidators.validate_config_data(data)

    if errors:
        return jsonify({'success': False, 'errors': errors}), 400

    user_role_id = getattr(current_user, 'role_id', 1)
    user_id = getattr(current_user, 'id', None)

    WasteConfigService.update_configs(
        data=data, 
        current_user_role_id=user_role_id, 
        user_id=user_id
    )
    
    return jsonify({'success': True, 'message': 'Parámetros actualizados correctamente'})