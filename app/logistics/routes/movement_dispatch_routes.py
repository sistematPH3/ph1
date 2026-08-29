from flask import Blueprint, render_template, request, jsonify, flash
from flask_login import login_required, current_user
from app.models import Location, Product
from app.logistics.services.movement_dispatch_service import MovementDispatchService
from app.decorators.roles import require_roles

dispatch_bp = Blueprint('dispatch_bp', __name__)

@dispatch_bp.route('/dispatch', methods=['GET'])
@login_required
@require_roles('admin')
def dispatch_form_view():
    locations = Location.query.filter_by(is_active=True).all()
    products = Product.query.filter_by(is_active=True).all()

    # Se captura el id de la disputa si viene como parámetro en la URL
    dispute_id = request.args.get('dispute_id')

    user_location_id = None
    if hasattr(current_user, 'locations') and current_user.locations:
        user_location_id = current_user.locations[0].id
    elif hasattr(current_user, 'location_id'):
        user_location_id = current_user.location_id

    is_admin = getattr(current_user, 'role_id', None) == 1
    user_role_id = getattr(current_user, 'role_id', None)
    user_role_name = getattr(current_user, 'role_name', None)
    is_read_only = user_role_id in [5, 6] or user_role_name in ['management', 'finance']

    return render_template(
        'logistics/movement_dispatch.html',
        is_read_only=is_read_only,
        locations=locations,
        products=products,
        user_location_id=user_location_id,
        is_admin=is_admin,
        dispute_id=dispute_id  # Se pasa a la plantilla HTML
    )

@dispatch_bp.route('/get-product-lots', methods=['GET'])
@login_required
def get_product_lots_api():
    location_id = request.args.get('location_id', type=int)
    product_id = request.args.get('product_id', type=int)

    response, status_code = MovementDispatchService.get_lots_for_dispatch(location_id, product_id)
    return jsonify(response), status_code

@dispatch_bp.route('/dispatch', methods=['POST'])
@login_required
@require_roles('admin')
def create_dispatch_api():
    payload = request.get_json()
    response, status_code = MovementDispatchService.execute_dispatch(current_user, payload)
    if status_code == 200 and isinstance(response, dict) and response.get("success"):
        flash(response.get("message") or "Despacho emitido exitosamente.", "traslado")
    return jsonify(response), status_code

@dispatch_bp.route('/cancel-dispatch/<int:movement_id>', methods=['POST'])
@login_required
@require_roles('admin')
def cancel_pre_dispatch(movement_id):
    data = request.get_json() or {}
    reason = data.get('reason', '')

    result, status_code = MovementDispatchService.execute_precancellation(current_user, movement_id, reason)
    return jsonify(result), status_code