from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from sqlalchemy import func
from app.models import Location, Product, Inventory, PurchaseDetail, PurchaseDetail, Movement, MovementDetail
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

    # Determinar si el usuario tiene rol de Administrador (role_id = 1)
    is_admin = getattr(current_user, 'role_id', None) == 1
    
    return render_template(
        '/logistics/movement_dispatch.html',
        locations=locations,
        products=products,
        user_location_id=user_location_id,
        is_admin=is_admin
    )

@dispatch_bp.route('/get-product-lots', methods=['GET'])
@login_required
def get_product_lots_api():
    location_id = request.args.get('location_id', type=int)
    product_id = request.args.get('product_id', type=int)

    if not location_id or not product_id:
        return jsonify({"success": False, "total_stock": 0, "lots": []}), 400

    inventory_item = Inventory.query.filter_by(
        location_id=location_id,
        product_id=product_id
    ).first()

    total_stock = float(inventory_item.current_quantity) if inventory_item else 0.0

    if total_stock <= 0:
        return jsonify({"success": True, "total_stock": 0, "lots": []}), 200

    # 1. Obtener total ingresado por lote
    purchased_query = db.session.query(
        PurchaseDetail.lot_number,
        PurchaseDetail.expiration_date,
        func.sum(PurchaseDetail.quantity).label('total_purchased')
    ).filter(
        PurchaseDetail.product_id == product_id,
        PurchaseDetail.lot_number.isnot(None),
        PurchaseDetail.lot_number != ''
    ).group_by(
        PurchaseDetail.lot_number,
        PurchaseDetail.expiration_date
    ).all()

    # 2. Obtener total despachado/descontado por lote desde la sede de origen
    dispatched_query = db.session.query(
        MovementDetail.lot_number,
        func.sum(MovementDetail.quantity).label('total_dispatched')
    ).join(
        Movement, Movement.id == MovementDetail.movement_id
    ).filter(
        MovementDetail.product_id == product_id,
        Movement.origin_location_id == location_id,
        Movement.status.in_(['COMPLETED', 'EN_TRANSITO'])
    ).group_by(
        MovementDetail.lot_number
    ).all()

    # Mapear salidas por número de lote
    dispatched_map = {item.lot_number: float(item.total_dispatched or 0) for item in dispatched_query}

    # 3. Calcular disponibilidad neta por lote
    lots = []
    for item in purchased_query:
        purchased_qty = float(item.total_purchased or 0)
        dispatched_qty = dispatched_map.get(item.lot_number, 0.0)
        available_qty = max(0.0, purchased_qty - dispatched_qty)

        if available_qty > 0:
            lots.append({
                "lot_number": item.lot_number,
                "available_quantity": available_qty,
                "expiration_date": item.expiration_date.strftime('%Y-%m-%d') if item.expiration_date else ''
            })

    return jsonify({
        "success": True,
        "total_stock": total_stock,
        "lots": lots
    }), 200

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