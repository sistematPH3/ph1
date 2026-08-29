from flask import render_template, Blueprint
from flask_login import login_required, current_user
from app.decorators.roles import require_roles  
from app.logistics.services.movement_list_service import get_movement_list_context

logistics_list_bp = Blueprint('logistics_list', __name__)

@logistics_list_bp.route('/logistics/movements', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations', 'finance')
def movement_list():
    # Obtenemos el diccionario con el contexto completo desde el servicio
    data = get_movement_list_context(current_user)
    
    # Renderizamos la plantilla pasando la nueva variable de arbitraje
    return render_template(
        'logistics/movement_list.html',
        en_camino=data["en_camino"],
        por_recibir=data["por_recibir"],
        arbitraje=data["arbitraje"],
        historico=data["historico"],
        user_location_ids=data["user_location_ids"]
    )