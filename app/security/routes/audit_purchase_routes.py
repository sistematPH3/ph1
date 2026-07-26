from flask import Blueprint, render_template
from app.extensions import db
from app.models import PurchaseAuditLog, User, Role
from app.decorators.roles import require_roles
from datetime import timedelta

audit_purchase_bp = Blueprint('audit_purchase', __name__)

@audit_purchase_bp.route('/auditoria/compras', methods=['GET'])
@require_roles('admin', 'finance')
def list_purchase_audits():
    results = db.session.query(PurchaseAuditLog, User, Role)\
        .outerjoin(User, PurchaseAuditLog.user_id == User.id)\
        .outerjoin(Role, User.role_id == Role.id)\
        .order_by(PurchaseAuditLog.timestamp.desc())\
        .all()
    
    audits_list = []
    
    for audit, user, role in results:
        changed_data = {}
        
        if audit.action_type == 'CREATE':
            if audit.new_data:
                changed_data = {
                    'monto total': {
                        'old': '', 
                        'new': f"{audit.new_data.get('total_amount', 0)} {audit.new_data.get('currency', '')}"
                    }
                }
        elif audit.action_type == 'EDIT':
            if audit.new_data:
                changed_data = {
                    'motivo de edición': {
                        'old': '', 
                        'new': audit.new_data.get('edit_reason', 'Modificación de insumos')
                    }
                }
        elif audit.action_type == 'ANNULLED':
            changed_data = {
                'estado de factura': {
                    'old': 'COMPLETED',
                    'new': 'ANULADA (Stock Revertido)'
                }
            }

        local_time = audit.timestamp - timedelta(hours=4) if audit.timestamp else None

        audits_list.append({
            'id': audit.id,
            'purchase_id': audit.purchase_id,
            'action_type': audit.action_type,
            'timestamp': local_time,
            'changed_data': changed_data,
            'user_name': user.name if user else 'Sistema',
            'role_name': role.name if role else 'Administrador',
            'user_initial': user.name[:1].upper() if user else 'S'
        })

    return render_template('security/audit_purchase.html', audits=audits_list)