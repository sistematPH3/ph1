from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.decorators.roles import require_roles, require_roles_api
from app.inventory.requests.kitchen_expense_audit_validators import (
    validate_kitchen_expense_action,
    validate_kitchen_expense_filters,
)
from app.inventory.services.kitchen_expense_audit_service import (
    get_consumption_date_range,
    get_kitchen_expense_counts,
    get_kitchen_expense_entries,
    get_kitchen_expense_locations,
    process_kitchen_expense_action,
)

kitchen_expense_audit_bp = Blueprint('kitchen_expense_audit', __name__)

KITCHEN_EXPENSE_VIEW_ROLES = ('admin', 'management', 'manager', 'assistant_manager', 'finance')
KITCHEN_EXPENSE_WRITE_ROLES = ('admin', 'management', 'manager', 'assistant_manager')


@kitchen_expense_audit_bp.route('/inventory/expenses/audit', methods=['GET'])
@login_required
@require_roles(*KITCHEN_EXPENSE_VIEW_ROLES)
def view_kitchen_expense_audit():
    filters = validate_kitchen_expense_filters(request.args)

    role_id = getattr(current_user, 'role_id', None)
    is_admin = (role_id == 1)

    entries = get_kitchen_expense_entries(filters, current_user, is_admin)
    counts = get_kitchen_expense_counts(filters, current_user, is_admin)
    locations = get_kitchen_expense_locations(current_user, is_admin)

    date_min, date_max = get_consumption_date_range(filters, current_user, is_admin)
    date_min_str = date_min.strftime('%Y-%m-%d') if date_min else ''
    date_max_str = date_max.strftime('%Y-%m-%d') if date_max else ''

    return render_template(
        'inventory/kitchen_expense_audit.html',
        is_admin=is_admin,
        locations=locations,
        entries=entries,
        counts=counts,
        active_tab=filters.get('tab', 'gastos'),
        filters=filters,
        date_min=date_min_str,
        date_max=date_max_str,
    )


@kitchen_expense_audit_bp.route('/inventory/api/expenses/audit/action', methods=['POST'])
@require_roles_api(*KITCHEN_EXPENSE_WRITE_ROLES)
def execute_kitchen_expense_action():
    data = request.get_json()

    validation = validate_kitchen_expense_action(data)
    if not validation['is_valid']:
        return jsonify({
            'success': False,
            'message': 'Datos inválidos',
            'errors': validation['errors'],
        }), 400

    result = process_kitchen_expense_action(
        log_id=data.get('log_id'),
        current_user=current_user,
        action_type=data.get('action_type'),
        new_quantity_requested=data.get('new_quantity'),
        justification_notes=data.get('notes'),
        lot_number=data.get('lot_number'),
    )

    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code