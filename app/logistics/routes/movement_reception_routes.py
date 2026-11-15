from flask import Blueprint, render_template, request, jsonify, redirect, flash, session
from flask_login import current_user, login_required
from app.decorators.roles import require_roles
from app.models import Product
from app.logistics.services.movement_reception_service import MovementReceptionService
from app.logistics.requests.movement_reception_validators import (
    is_lot_mismatch_contradiction,
    is_near_expiry_contradiction,
)

movement_reception_bp = Blueprint("movement_reception", __name__, url_prefix="/logistics/movements")

def _resolve_user_context():
    """Deriva (user_id, user_role_id, user_location_ids) del usuario o de la sesión."""
    user_id = current_user.id if hasattr(current_user, 'id') else session.get("user_id")
    user_role_id = getattr(current_user, 'role_id', None) or session.get("role_id")

    user_location_ids = []
    if hasattr(current_user, 'locations'):
        user_location_ids = [loc.id for loc in current_user.locations]
    elif hasattr(current_user, 'location_id') and current_user.location_id:
        user_location_ids = [current_user.location_id]
    else:
        user_location_ids = session.get("location_ids", [])

    return user_id, user_role_id, user_location_ids

@movement_reception_bp.route("/reception/<int:movement_id>", methods=["GET"])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def view_reception(movement_id):
    user_id, user_role_id, user_location_ids = _resolve_user_context()

    data, error = MovementReceptionService.get_reception_data(movement_id, user_location_ids, user_role_id)
    if error:
        flash(error, "recibido-error")
        return redirect("/logistics/movements")

    catalog_products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()

    # El 'Rechazo por Espacio' solo tiene sentido en el flujo de abastecimiento
    # Central -> sede. En devoluciones sede -> Central (RETORNO_EMERGENCIA) se
    # oculta la opción (el servicio además la bloquea por API).
    from app.logistics.requests.movement_dispatch_validators import CENTRAL_LOCATION_ID
    allow_rechazo_por_espacio = (
        data["movement"]["type"] != "RETORNO_EMERGENCIA"
        and data["movement"]["origin_location_id"] == CENTRAL_LOCATION_ID
    )

    return render_template(
        "logistics/movement_reception.html",
        movement=data["movement"],
        details=data["details"],
        catalog_products=catalog_products,
        allow_rechazo_por_espacio=allow_rechazo_por_espacio
    )

@movement_reception_bp.route("/reception/lot-expiration", methods=["GET"])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def reception_lot_expiration():
    """Devuelve la fecha de vencimiento de un lote físico capturado en muelle.

    Cuando el lote no coincide con la guía, el operario escribe el lote real que llegó;
    esta consulta intenta recuperar su fecha de vencimiento desde el histórico para
    autocompletarla (el lote y su vencimiento van juntos).
    """
    product_id = request.args.get("product_id", type=int)
    lot_number = request.args.get("lot_number", "").strip()

    result = MovementReceptionService.get_lot_expiration(product_id, lot_number)
    return jsonify({
        "success": True,
        "lot_number": lot_number,
        "exists": result["exists"],
        "expiration_date": result["expiration_date"]
    }), 200

@movement_reception_bp.route("/reception/<int:movement_id>/process", methods=["POST"])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def process_reception(movement_id):
    user_id, user_role_id, user_location_ids = _resolve_user_context()

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
        # Las contradicciones explícitas (lote igual a la guía o "Vencimiento
        # Próximo" sin sustento) son errores de datos del cliente (400); el resto
        # de validaciones conserva el 422 existente.
        if is_lot_mismatch_contradiction(message):
            return jsonify({"success": False, "message": message}), 400
        if is_near_expiry_contradiction(message):
            errores = message if isinstance(message, list) else [message]
            return jsonify({
                "success": False,
                "code": "VENCIMIENTO_PROXIMO_INVALIDO",
                "message": message,
                "errors": errores,
            }), 400
        return jsonify({"success": False, "message": message}), 422

    flash("Cargamento recibido y procesado con éxito.", "recibido")
    return jsonify({
        "success": True,
        "message": message,
        "redirect_url": "/logistics/movements"
    }), 200