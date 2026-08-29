# app/logistics/routes/movement_dispute_routes.py
#
# Controlador HTTP del sub-módulo de Arbitraje / Bandeja de Novedades.
# Sin lógica de negocio: delega en app/logistics/services/movement_dispute_service.py.

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, get_flashed_messages
from flask_login import current_user, login_required
from app.decorators.roles import require_roles
from app.logistics.services.movement_dispute_service import (
    get_disputes_context,
    resolve_dispute as service_resolve_dispute,
    cancel_linked_replenishment as service_cancel_replenishment,
)

movement_dispute_bp = Blueprint("movement_dispute", __name__, url_prefix="/logistics/movements/admin/disputes")


@movement_dispute_bp.route("/", methods=["GET"], endpoint="list_disputes")
@movement_dispute_bp.route("/index", methods=["GET"], endpoint="admin_disputes")
@login_required
@require_roles('admin', 'manager', 'assistant_manager')
def list_disputes():
    """Muestra la bandeja de novedades, incidencias o disputas de los traslados."""
    try:
        disputes, locations = get_disputes_context()
        # Los mensajes del módulo de disputas se muestran y consumen AQUÍ;
        # las demás categorías (recepción, traslado, etc.) se re-encolan
        # para no perderse ni mostrarse en este archivo.
        dispute_flashes = []
        for category, msg in get_flashed_messages(with_categories=True):
            if category.startswith("dispute"):
                dispute_flashes.append((category, msg))
            else:
                flash(msg, category)
        return render_template(
            "logistics/movement_dispute.html",
            disputes=disputes,
            locations=locations,
            dispute_flashes=dispute_flashes
        )
    except Exception as e:
        flash(f"Error al cargar la bandeja de novedades: {str(e)}", "dispute-error")
        return redirect(url_for('movement_dispute.list_disputes'))


@movement_dispute_bp.route("/<int:movement_id>/resolve", methods=["POST"])
@login_required
@require_roles('admin', 'manager')
def resolve_dispute(movement_id):
    """Procesa el veredicto granular de la disputa (delegado al servicio)."""
    try:
        payload = request.form or request.get_json() or {}
        service_resolve_dispute(movement_id, payload, user_id=current_user.id)
        flash(f"Disputa #{movement_id} resuelta exitosamente y saldos actualizados.", "dispute")
    except Exception as e:
        flash(f"Error al resolver la disputa: {str(e)}", "dispute-error")
    return redirect(url_for('movement_dispute.list_disputes'))


@movement_dispute_bp.route("/<int:movement_id>/cancel-replenishment", methods=["POST"])
@login_required
@require_roles('admin', 'manager', 'assistant_manager')
def cancel_linked_replenishment(movement_id):
    """Cancela el traslado de reposición si la disputa se abandona (delegado al servicio)."""
    try:
        ok, message = service_cancel_replenishment(movement_id)
        return jsonify({"success": ok, "message": message}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"Error al revertir reposición: {str(e)}"}), 500