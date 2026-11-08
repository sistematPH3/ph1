from flask import Blueprint, render_template
from flask_login import current_user

from app.decorators.roles import require_roles
from app.security.services.audit_purchase_service import AuditPurchaseService

audit_purchase_bp = Blueprint('audit_purchase', __name__)


@audit_purchase_bp.route('/auditoria/compras', methods=['GET'])
@require_roles('admin')
def list_purchase_audits():
    audits = AuditPurchaseService.list_purchase_audits(current_user)
    return render_template('security/audit_purchase.html', audits=audits)