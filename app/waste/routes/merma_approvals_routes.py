"""Controlador HTTP de la bandeja de aprobaciones de mermas.

Parte 3 de la propuesta (Módulo de Mermas). Reúne en un solo archivo la lista
de mermas en espera y la bandeja donde el Administrador decide aprobar o
rechazar. Sin lógica de negocio: se delega en merma_approvals_service.py.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.waste.requests.merma_approvals_validators import validate_resolution_payload
from app.waste.services import merma_approvals_service as svc

merma_approvals_bp = Blueprint('merma_approvals', __name__)


@merma_approvals_bp.route('/waste/merma/approvals', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations', 'finance')
def bandeja_aprobaciones():
    """Página de la bandeja de mermas pendientes.

    Muestra la cola de mermas en espera. El Administrador ve todas y puede
    aprobar/rechazar; el resto ve solo sus sedes en modo lectura.
    """
    return render_template(
        'waste/merma_approvals.html',
        is_admin=bool(getattr(current_user, 'is_admin', False)),
    )


@merma_approvals_bp.route('/api/waste/merma/approvals', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations', 'finance')
def bandeja_api():
    """JSON con las mermas pendientes (filtradas por la sede del usuario)."""
    try:
        pendientes = svc.get_pending_wastes(current_user.id)
        return jsonify({'success': True, 'wastes': pendientes}), 200
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Error al listar mermas: {str(exc)}'}), 500


@merma_approvals_bp.route('/api/waste/merma/pending-summary', methods=['GET'])
@login_required
@require_roles('admin')
def pending_summary():
    """Resumen en vivo de mermas pendientes de resolución (círculo del sidebar)."""
    try:
        return jsonify(svc.get_pending_waste_summary(current_user.id)), 200
    except Exception as exc:
        return jsonify({'pending_count': 0, 'items': [], 'error': str(exc)}), 500


@merma_approvals_bp.route('/api/waste/merma/<int:waste_id>', methods=['GET'])
@login_required
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations', 'finance')
def detalle_merma(waste_id):
    """Detalle de una merma: cabecera + líneas (producto, lote, stock)."""
    try:
        data, error = svc.get_waste_detail(waste_id, current_user.id)
        if error:
            return jsonify({'success': False, 'message': error}), 403
        data['is_admin'] = bool(getattr(current_user, 'is_admin', False))
        return jsonify({'success': True, 'waste': data}), 200
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Error al cargar el detalle: {str(exc)}'}), 500


@merma_approvals_bp.route('/api/waste/merma/<int:waste_id>/approve', methods=['POST'])
@login_required
@require_roles('admin')
def aprobar_merma(waste_id):
    """Admin aprueba una merma pendiente: descuenta stock + audita + notifica."""
    try:
        result = svc.approve_waste(waste_id, current_user.id)
    except PermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Error interno: {str(exc)}'}), 500
    code = 200 if result['success'] else 400
    return jsonify(result), code


@merma_approvals_bp.route('/api/waste/merma/<int:waste_id>/reject', methods=['POST'])
@login_required
@require_roles('admin')
def rechazar_merma(waste_id):
    """Admin rechaza una merma pendiente: no toca stock + audita + notifica."""
    data = request.get_json(silent=True) or {}
    validation = validate_resolution_payload(data, 'reject')
    if not validation['is_valid']:
        return jsonify({'success': False, 'errors': validation['errors']}), 400
    try:
        result = svc.reject_waste(waste_id, current_user.id, data.get('reason'))
    except PermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Error interno: {str(exc)}'}), 500
    code = 200 if result['success'] else 400
    return jsonify(result), code
