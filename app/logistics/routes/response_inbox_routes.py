from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
# Importamos la función con el nombre correcto
from app.decorators.roles import require_roles 
from app.logistics.repositories.response_inbox_repository import ResponseInboxRepository
from app.logistics.services.response_inbox_service import ResponseInboxService

inbox_bp = Blueprint('response_inbox', __name__)

# Opciones de los filtros de la bandeja (búsqueda por texto, clasificación de
# la novedad y sucursal involucrada). Se calculan a partir de las respuestas
# visibles para cada usuario para no ofrecer filtros vacíos.
def _inbox_filter_context(responses):
    novedades, sedes = {}, {}
    for mov in responses:
        ntype = getattr(mov, 'novedad_type', None)
        if ntype and ntype not in novedades:
            novedades[ntype] = mov.novedad_label or ntype.replace('_', ' ').title()
        for loc in (getattr(mov, 'origin_location', None),
                    getattr(mov, 'destination_location', None)):
            if loc is not None:
                sedes.setdefault(loc.id, loc.name)
    return novedades, sedes


@inbox_bp.route('/logistics/movements/responses', methods=['GET'])
@login_required
# Usamos los nombres exactos en minúscula según tu mapeo en roles.py
# 'operations' son los receptores de traslados en las sucursales: también
# deben ver las respuestas del administrador a las novedades que reportaron.
@require_roles('admin', 'manager', 'assistant_manager', 'management', 'finance', 'operations')
def admin_responses():
    responses = ResponseInboxService.get_responses_for_user(current_user)
    # División determinista: dos apartados en la bandeja.
    responses_unread = [m for m in responses if not m.is_read]
    responses_read = [m for m in responses if m.is_read]
    filter_novedades, filter_sedes = _inbox_filter_context(responses)

    return render_template(
        'logistics/response_inbox.html',
        responses=responses,
        responses_unread=responses_unread,
        responses_read=responses_read,
        unread_count=ResponseInboxRepository.get_unread_count(current_user),
        filter_novedades=filter_novedades,
        filter_sedes=filter_sedes
    )


@inbox_bp.route('/logistics/movements/responses/summary', methods=['GET'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager', 'management', 'finance', 'operations')
def inbox_summary():
    """JSON con las respuestas recientes para la campana de notificaciones.

    Lo consume la campana (polling ligero) para pintar el contador de
    respuestas sin leer (calculado en el servidor) y el extracto de las más
    recientes. No expone datos sensibles: solo id del traslado, sedes, fecha
    y un extracto del acta.
    """
    try:
        return jsonify(ResponseInboxService.get_inbox_summary(current_user))
    except Exception as e:
        return jsonify({"error": str(e), "total": 0, "unread_count": 0, "items": []}), 500


@inbox_bp.route('/logistics/movements/responses/read', methods=['POST'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager', 'management', 'finance', 'operations')
def mark_response_read():
    """Marca como leída la respuesta de un traslado (estado en el servidor)."""
    try:
        payload = request.get_json(silent=True) or {}
        movement_id = payload.get('movement_id')
        if movement_id is None:
            return jsonify({"error": "movement_id requerido"}), 400
        ResponseInboxService.mark_as_read(current_user, int(movement_id))
        return jsonify({
            "success": True,
            "unread_count": ResponseInboxRepository.get_unread_count(current_user),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@inbox_bp.route('/logistics/movements/responses/read-all', methods=['POST'])
@login_required
@require_roles('admin', 'manager', 'assistant_manager', 'management', 'finance', 'operations')
def mark_all_responses_read():
    """Marca todas las respuestas del usuario como leídas en el servidor."""
    try:
        marked = ResponseInboxService.mark_all_as_read(current_user)
        return jsonify({"success": True, "marked": marked, "unread_count": 0})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500