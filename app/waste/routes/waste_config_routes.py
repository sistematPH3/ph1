from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required

from app.decorators.roles import require_roles
from app.waste.services.waste_config_service import WasteConfigService
from app.waste.requests.waste_config_validators import WasteConfigValidators

waste_config_bp = Blueprint('waste_config', __name__)


@waste_config_bp.route('/waste/merma/config', methods=['GET'])
@login_required
@require_roles('admin')
def configuracion():
    configs = WasteConfigService.get_config_data()
    return render_template('waste/waste_config.html', configs=configs)


@waste_config_bp.route('/api/waste/merma/config', methods=['POST'])
@login_required
@require_roles('admin')
def guardar_config():
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    errors = WasteConfigValidators.validate_config_data(data)

    if errors:
        mensaje = ' '.join(f'{campo}: {texto}' for campo, texto in errors.items())
        return jsonify({'success': False, 'errors': errors, 'message': mensaje}), 400

    WasteConfigService.update_configs(data)

    return jsonify({'success': True, 'message': 'Parámetros actualizados correctamente'})