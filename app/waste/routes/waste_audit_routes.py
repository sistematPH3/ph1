from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.models.waste_model import WasteType
from app.models.logistics_model import Location
from app.waste.services.waste_audit_service import WasteAuditService
from app.waste.requests.waste_audit_validators import validate_audit_filters
from app.decorators.roles import require_roles
import json

waste_audit_bp = Blueprint('waste_audit', __name__, url_prefix='/waste/merma')

@waste_audit_bp.route('/audit', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def ver_auditoria():
    """Renderiza la vista principal pasando los datos directamente a Jinja2."""
    try:
        locations = Location.query.filter_by(is_active=True).all()
        # Mapear nombres de las sedes
        locations_list = [getattr(loc, 'nombre', None) or getattr(loc, 'name', '') for loc in locations]
        locations_list = [loc for loc in locations_list if loc]
    except Exception:
        locations_list = []

    # Obtener el historial completo
    raw_audit_trail = WasteAuditService.get_formatted_audit_trail(current_user, {})

    # Normalizar los datos para evitar fallos si 'changed_data' o 'details' llegaron como string
    audit_trail = []
    for item in raw_audit_trail:
        if isinstance(item, dict):
            # Si cambió_data o un campo interno viene como string JSON, se parsea a dict
            changed = item.get('changed_data') or item.get('details')
            if isinstance(changed, str):
                try:
                    item['changed_data'] = json.loads(changed)
                except (json.JSONDecodeError, TypeError):
                    item['changed_data'] = {'detalle': changed}
            audit_trail.append(item)
        else:
            # Si el elemento completo de la lista era un string
            audit_trail.append({'detalle': str(item)})

    return render_template(
        'waste/waste_audit.html', 
        audit_trail=audit_trail, 
        locations=locations_list
    )

@waste_audit_bp.route('/api/audit', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def auditoria_api():
    """Endpoint API que retorna los eventos en formato JSON."""
    errors = validate_audit_filters(request.args)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400
        
    filters = {
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'severity': request.args.get('severity')
    }
    
    audit_trail = WasteAuditService.get_formatted_audit_trail(current_user, filters)
    return jsonify({'success': True, 'data': audit_trail}), 200


@waste_audit_bp.route('/locations/api/all', methods=['GET'])
@login_required
def get_all_locations():
    try:
        # Consulta de sedes activas desde la base de datos
        sedes = Location.query.filter_by(is_active=True).all()
        data = [getattr(sede, 'nombre', None) or getattr(sede, 'name', '') for sede in sedes]
        return jsonify({'success': True, 'data': [d for d in data if d]}), 200
    except Exception as e:
        return jsonify({'success': False, 'errors': [str(e)]}), 500

def obtener_tipos_merma_por_sede(location_id: int):
    """
    Sede Central (location_id = 1) solo maneja mermas de TEMPERATURA y ROBO_SOSPECHA.
    Las demás sedes (con cocina) disponen del catálogo completo.
    """
    if location_id == 1:
        return WasteType.query.filter(
            WasteType.is_active == True,
            WasteType.code.in_(['TEMPERATURA', 'ROBO_SOSPECHA'])
        ).all()
    
    return WasteType.query.filter(WasteType.is_active == True).all()
