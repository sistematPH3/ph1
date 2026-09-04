"""Listado de mermas pendientes del propio usuario (para editar o cancelar).

Contiene la página "Mis Mermas Pendientes" y la acción de CANCELAR (funcional,
con confirmación y auditoría). La EDICIÓN (Parte 5 del módulo) la implementa el
compañero en merma_edit; sin embargo, el evento de auditoría MERMA_EDITADA ya
se renderiza en la Auditoría de Inventario.
"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.waste.requests.merma_approvals_validators import validate_resolution_payload
from app.waste.services import merma_approvals_service as svc

merma_list_bp = Blueprint('merma_list', __name__)


@merma_list_bp.route('/waste/merma/mis-pendientes', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def mis_pendientes():
    """Página con las mermas PENDIENTES visibles para el usuario.

    Admin: todas las sedes. Resto: sus sedes asignadas. Solo el autor puede
    corregir/cancelar su propia merma mientras siga pendiente.
    """
    pendientes, is_admin = svc.get_pending_wastes_for_view(current_user.id)
    return render_template(
        'waste/merma_list.html',
        pendientes=pendientes,
        pending_count=len(pendientes),
        is_admin=is_admin,
    )


@merma_list_bp.route('/api/waste/merma/<int:waste_id>/cancel', methods=['POST'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def cancelar_merma(waste_id):
    """El autor retira su merma PENDIENTE (confirmación previa en el cliente)."""
    data = request.get_json(silent=True) or {}
    validation = validate_resolution_payload(data, 'cancel')
    if not validation['is_valid']:
        return jsonify({'success': False, 'errors': validation['errors']}), 400
    try:
        result = svc.cancel_waste(waste_id, current_user.id, data.get('reason'))
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Error interno: {str(exc)}'}), 500
    code = 200 if result['success'] else 400
    return jsonify(result), code