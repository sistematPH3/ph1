from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import login_required, current_user
from app.decorators.roles import require_roles
from app.waste.services.waste_edit_service import WasteEditService

waste_edit_bp = Blueprint("waste_edit", __name__)

OPERATIVE_ROLES = ("admin", "management", "manager", "assistant_manager", "operations")

@waste_edit_bp.route("/waste/merma/<int:waste_id>/edit", methods=["GET"])
@login_required
@require_roles(*OPERATIVE_ROLES)
def editar_merma(waste_id):
    user_id = session.get("user_id") or session.get("_user_id") or getattr(current_user, "id", None)
    is_admin = bool(getattr(current_user, "is_admin", False) or getattr(current_user, "role_id", None) == 1)

    data, error = WasteEditService.get_waste_for_edit(waste_id, user_id, is_admin)
    if error:
        flash(error, "danger")
        return redirect(url_for("waste_approvals.bandeja_aprobaciones"))

    return render_template(
        "waste/waste_edit.html",
        waste=data,
        is_admin=is_admin
    )

@waste_edit_bp.route("/api/waste/merma/<int:waste_id>/edit", methods=["GET", "POST"])
@login_required
@require_roles(*OPERATIVE_ROLES)
def guardar_edicion(waste_id):
    user_id = session.get("user_id") or session.get("_user_id") or getattr(current_user, "id", None)
    is_admin = bool(getattr(current_user, "is_admin", False) or getattr(current_user, "role_id", None) == 1)

    if request.method == "GET":
        data, error = WasteEditService.get_waste_for_edit(waste_id, user_id, is_admin)
        if error:
            code = 404 if "existe" in error else 403
            return jsonify({"success": False, "message": error}), code
        if not data["can_edit"]:
            return jsonify({
                "success": False,
                "message": "Esta merma ya no es editable: no tiene permisos o la ventana de tiempo expiró."
            }), 403
        return jsonify({"success": True, "waste": data}), 200

    payload = request.get_json(silent=True) or {}
    response_data, status_code = WasteEditService.edit_pending_waste(waste_id, payload, user_id, is_admin)
    return jsonify(response_data), status_code

@waste_edit_bp.route("/api/waste/merma/<int:waste_id>/revert", methods=["POST"])
@login_required
@require_roles("admin")
def revertir_merma(waste_id):
    user_id = session.get("user_id") or session.get("_user_id") or getattr(current_user, "id", None)
    is_admin = bool(getattr(current_user, "is_admin", False) or getattr(current_user, "role_id", None) == 1)

    payload = request.get_json(silent=True) or {}
    response_data, status_code = WasteEditService.revert_approved_waste(waste_id, payload, user_id, is_admin)
    return jsonify(response_data), status_code