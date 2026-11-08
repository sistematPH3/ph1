from flask import Blueprint, render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from app.decorators.roles import require_roles
from app.security.services.audit_user_service import AuditUserService

audit_user_bp = Blueprint('audit_user', __name__, url_prefix='/auditoria')

@audit_user_bp.route('/usuarios', methods=['GET'])
@login_required
@require_roles('admin')
def list_user_audits():
    # 2. Pasamos el 'current_user' al servicio para evaluar su rol y sedes
    audits = AuditUserService.get_audit_history(current_user=current_user)
    
    return render_template('security/audit_user.html', audits=audits)