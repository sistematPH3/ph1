from flask import Blueprint, request, jsonify, render_template, session
from flask_login import login_required
from app.decorators.roles import require_roles, require_roles_api
from app.inventory.requests.register_consumption_validators import validate_consumption_payload
from app.inventory.services.register_consumption_service import (
    register_consumption, 
    get_consumption_form_data, 
    get_location_products,
    get_product_lots,
    user_can_access_location
)

register_consumption_bp = Blueprint('register_consumption', __name__)

OPERATIVE_ROLES = ('admin', 'management', 'manager', 'assistant_manager', 'operations')

@register_consumption_bp.route('/inventory/register-consumption', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def show_consumption_form():
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id')
    
    if user_id:
        user_id = int(user_id)
        
    locations, is_admin = get_consumption_form_data(user_id)
    return render_template(
        'inventory/register_consumption.html', 
        locations=locations, 
        is_admin=is_admin
    )

@register_consumption_bp.route('/api/inventory/locations/<int:location_id>/products', methods=['GET'])
@require_roles_api(*OPERATIVE_ROLES)
def fetch_location_products(location_id):
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id')

    if not user_can_access_location(user_id, location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar el inventario de esta sede.'}), 403

    products = get_location_products(location_id)
    return jsonify({'success': True, 'products': products}), 200

@register_consumption_bp.route('/api/inventory/locations/<int:location_id>/products/<int:product_id>/lots', methods=['GET'])
@require_roles_api(*OPERATIVE_ROLES)
def fetch_product_lots(location_id, product_id):
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id')

    if not user_can_access_location(user_id, location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar los lotes de esta sede.'}), 403

    lots = get_product_lots(location_id, product_id)
    return jsonify({'success': True, 'lots': lots}), 200

@register_consumption_bp.route('/api/inventory/register-consumption', methods=['POST'])
@require_roles_api(*OPERATIVE_ROLES)
def process_consumption():
    data = request.get_json()
    validation = validate_consumption_payload(data)

    if not validation['is_valid']:
        return jsonify({'success': False, 'errors': validation['errors']}), 400

    user_id = session.get('user_id') or session.get('_user_id') or session.get('id')

    if not user_can_access_location(user_id, data['location_id']):
        return jsonify({'success': False, 'message': 'No tienes permisos para registrar consumo en esta sede.'}), 403

    result = register_consumption(
        location_id=data['location_id'],
        items=data['items'],
        user_id=user_id
    )

    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400