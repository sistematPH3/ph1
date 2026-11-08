from flask import render_template, Blueprint, flash, get_flashed_messages
from flask_login import login_required, current_user
from app.decorators.roles import require_roles  
from app.logistics.services.movement_list_service import get_movement_list_context

logistics_list_bp = Blueprint('logistics_list', __name__)

@logistics_list_bp.route('/logistics/movements', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def movement_list():
    # Obtenemos el diccionario con el contexto completo desde el servicio
    data = get_movement_list_context(current_user)
    
    # Los mensajes de traslados (despacho) y recepción se muestran y consumen AQUÍ;
    # las demás categorías se re-encolan para no perderse ni mezclarse en este archivo.
    movement_flashes = []
    for category, msg in get_flashed_messages(with_categories=True):
        if category.startswith(("traslado", "recibido")):
            movement_flashes.append((category, msg))
        else:
            flash(msg, category)
    
    # Renderizamos la plantilla pasando la nueva variable de arbitraje
    return render_template(
        'logistics/movement_list.html',
        en_camino=data["en_camino"],
        por_recibir=data["por_recibir"],
        arbitraje=data["arbitraje"],
        historico=data["historico"],
        user_location_ids=data["user_location_ids"],
        movement_flashes=movement_flashes
    )