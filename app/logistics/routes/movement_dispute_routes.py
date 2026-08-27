from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.decorators.roles import admin_required
from app.models import Location
from app.logistics.repositories.movement_dispute_repository import MovementDisputeRepository
from app.logistics.services.movement_dispute_service import MovementDisputeService

movement_dispute_bp = Blueprint('movement_dispute', __name__)

@movement_dispute_bp.route('/logistics/movements/admin/disputes', methods=['GET'])
@login_required
@admin_required
def admin_disputes():
    disputes = MovementDisputeRepository.get_pending_disputes()
    locations = Location.query.filter_by(is_active=True).all()

    return render_template(
        'logistics/movement_dispute.html',
        disputes=disputes,
        locations=locations
    )

@movement_dispute_bp.route('/logistics/movements/admin/disputes/<int:movement_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_dispute(movement_id):
    action_type = request.form.get('action_type')
    resolution_notes = request.form.get('resolution_notes', '')

    try:
        MovementDisputeService.resolve_dispute(
            movement_id=movement_id,
            action_type=action_type,
            resolution_notes=resolution_notes,
            admin_user_id=current_user.id
        )
        flash('El veredicto administrativo ha sido procesado y asentado en auditoría.', 'success')
    except ValueError as ve:
        flash(str(ve), 'danger')
    except Exception as e:
        flash(f'Error inesperado en el arbitraje: {str(e)}', 'danger')

    return redirect(url_for('movement_dispute.admin_disputes'))