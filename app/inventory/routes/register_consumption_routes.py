from flask import Blueprint, request, jsonify, render_template, session
from app.inventory.requests.register_consumption_validators import validate_consumption_payload
from app.inventory.services.register_consumption_service import (
    register_consumption, 
    get_consumption_form_data, 
    get_location_products
)

register_consumption_bp = Blueprint('register_consumption', __name__)

@register_consumption_bp.route('/inventory/register-consumption', methods=['GET'])
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
def fetch_location_products(location_id):
    products = get_location_products(location_id)
    return jsonify({'success': True, 'products': products}), 200

@register_consumption_bp.route('/api/inventory/register-consumption', methods=['POST'])
def process_consumption():
    data = request.get_json()
    validation = validate_consumption_payload(data)

    if not validation['is_valid']:
        return jsonify({'success': False, 'errors': validation['errors']}), 400

    user_id = session.get('user_id') or session.get('_user_id') or session.get('id')

    result = register_consumption(
        data['product_id'],
        data['location_id'],
        data['quantity'],
        user_id,
        data.get('notes', '')
    )

    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400