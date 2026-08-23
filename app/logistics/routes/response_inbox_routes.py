from flask import Blueprint, render_template
from flask_login import login_required, current_user
# Importamos la función con el nombre correcto
from app.decorators.roles import require_roles 
from app.logistics.services.response_inbox_service import ResponseInboxService

inbox_bp = Blueprint('response_inbox', __name__)

@inbox_bp.route('/logistics/movements/responses', methods=['GET'])
@login_required
# Usamos los nombres exactos en minúscula según tu mapeo en roles.py
@require_roles('admin', 'manager', 'assistant_manager', 'management', 'finance')
def admin_responses():
    responses = ResponseInboxService.get_responses_for_user(current_user)
    
    return render_template(
        'logistics/response_inbox.html',
        responses=responses
    )