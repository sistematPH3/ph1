# app/logistics/routes/movement_audit_routes.py
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from app.decorators.roles import require_roles # Importamos tu decorador dinámico[cite: 11]
from app.logistics.requests.movement_audit_validators import validate_audit_filters
from app.logistics.services.movement_audit_service import MovementAuditService

logistics_audit_bp = Blueprint('logistics_audit', __name__)

@logistics_audit_bp.route('/logistics/movements/audit', methods=['GET'])
@login_required
@require_roles('admin', 'finance') # Acceso exclusivo para Admin y Finanzas[cite: 11]
def view_movement_audit():
    filters = validate_audit_filters(request.args)
    
    # REGLA DE NEGOCIO: Finanzas solo ve sus sedes asignadas. Admin ve todo.
    if current_user.is_finance and not current_user.is_admin:
        # Extraemos los IDs de las sedes asignadas al usuario de finanzas
        allowed_locations = [loc.id for loc in current_user.locations]
        filters['allowed_locations'] = allowed_locations
        
    audit_logs = MovementAuditService.get_structured_audits(filters)
    
    return render_template(
        'logistics/movement_audit.html',
        audit_logs=audit_logs,
        filters=filters
    )