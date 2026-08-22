from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.decorators.roles import admin_required
from app.logistics.repositories.movement_dispute_repository import MovementDisputeRepository
from app.logistics.services.movement_dispute_service import MovementDisputeService
from app.models import Location  # <--- 1. Importa el modelo Location aquí

movement_dispute_bp = Blueprint('movement_dispute', __name__)

@movement_dispute_bp.route('/logistics/movements/admin/disputes', methods=['GET'])
@login_required
@admin_required
def admin_disputes():
    disputes = MovementDisputeRepository.get_pending_disputes()
    locations = Location.query.all()  # <--- 2. Consulta todas las sedes disponibles
    
    return render_template(
        'logistics/movement_dispute.html', 
        disputes=disputes, 
        locations=locations  # <--- 3. Inyecta locations en la plantilla
    )

@movement_dispute_bp.route('/logistics/movements/admin/disputes/<int:movement_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_dispute(movement_id):
    action_type = request.form.get('action_type')
    resolution_notes = request.form.get('resolution_notes', '').strip()
    
    try:
        MovementDisputeService.resolve_dispute(
            movement_id=movement_id,
            action_type=action_type,
            resolution_notes=resolution_notes,
            admin_user_id=current_user.id
        )
        flash('La novedad ha sido arbitrada y cerrada exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al procesar el arbitraje: {str(e)}', 'danger')
        
    return redirect(url_for('movement_dispute.admin_disputes'))