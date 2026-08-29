from flask import Blueprint, render_template, request, jsonify, redirect, flash, session
from flask_login import current_user, login_required
from app.decorators.roles import require_roles
from app.models import Product
from app.logistics.services.movement_reception_service import MovementReceptionService

movement_reception_bp = Blueprint("movement_reception", __name__, url_prefix="/logistics/movements")

@movement_reception_bp.route("/reception/<int:movement_id>", methods=["GET"])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def view_reception(movement_id):
    user_id = current_user.id if hasattr(current_user, 'id') else session.get("user_id")
    user_role_id = getattr(current_user, 'role_id', None) or session.get("role_id")
    
    user_location_ids = []
    if hasattr(current_user, 'locations'):
        user_location_ids = [loc.id for loc in current_user.locations]
    elif hasattr(current_user, 'location_id') and current_user.location_id:
        user_location_ids = [current_user.location_id]
    else:
        user_location_ids = session.get("location_ids", [])

    data, error = MovementReceptionService.get_reception_data(movement_id, user_location_ids, user_role_id)
    if error:
        flash(error, "recibido-error")
        return redirect("/logistics/movements")

    catalog_products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()

    return render_template(
        "logistics/movement_reception.html",
        movement=data["movement"],
        details=data["details"],
        catalog_products=catalog_products
    )

@movement_reception_bp.route("/reception/<int:movement_id>/process", methods=["POST"])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def process_reception(movement_id):
    user_id = current_user.id if hasattr(current_user, 'id') else session.get("user_id")
    user_role_id = getattr(current_user, 'role_id', None) or session.get("role_id")
    
    user_location_ids = []
    if hasattr(current_user, 'locations'):
        user_location_ids = [loc.id for loc in current_user.locations]
    elif hasattr(current_user, 'location_id') and current_user.location_id:
        user_location_ids = [current_user.location_id]
    else:
        user_location_ids = session.get("location_ids", [])

    payload = request.get_json()
    if not payload:
        return jsonify({"success": False, "message": "Datos no proporcionados."}), 400

    success, message = MovementReceptionService.process_reception(
        movement_id=movement_id,
        user_id=user_id,
        user_role_id=user_role_id,
        user_location_ids=user_location_ids,
        payload=payload
    )

    if not success:
        return jsonify({"success": False, "message": message}), 422

    flash("Cargamento recibido y procesado con éxito.", "recibido")
    return jsonify({
        "success": True,
        "message": message,
        "redirect_url": "/logistics/movements"
    }), 200