from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.models import Location, Product, User
from app.logistics.services.movement_dispatch_service import MovementDispatchService
from app.decorators.roles import require_roles  # Decorador del proyecto

dispatch_bp = Blueprint('dispatch_bp', __name__, template_folder='templates')

@dispatch_bp.route('/dispatch', methods=['GET'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager')  # Solo Admin, Manager y Assistant Manager
def dispatch_form_view():
    """
    Renderiza la pantalla principal del formulario de emisión de despachos.
    """
    locations = Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).all()

    # Extrae el ID de la sede de forma segura
    user_location_id = None
    if hasattr(current_user, 'locations') and current_user.locations:
        user_location_id = current_user.locations[0].id
    elif hasattr(current_user, 'location_id'):
        user_location_id = current_user.location_id
    
    return render_template(
        '/logistics/movement_dispatch.html',
        locations=locations,
        products=products,
        user_location_id=user_location_id
    )

@dispatch_bp.route('/dispatch', methods=['POST'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager')
def create_dispatch_api():
    """
    Endpoint JSON para procesar el envío del formulario del carrito.
    """
    payload = request.get_json()
    response, status_code = MovementDispatchService.execute_dispatch(current_user, payload)
    return jsonify(response), status_code

@dispatch_bp.route('/cancel-dispatch/<int:movement_id>', methods=['POST'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager')
def cancel_pre_dispatch(movement_id):
    data = request.get_json() or {}
    reason = data.get('reason', '')
    
    result, status_code = MovementDispatchService.execute_precancellation(current_user, movement_id, reason)
    return jsonify(result), status_code