from flask import Blueprint, render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from app.security.services.audit_user_service import AuditUserService

audit_user_bp = Blueprint('audit_user', __name__, url_prefix='/auditoria')

@audit_user_bp.route('/usuarios', methods=['GET'])
@login_required
def list_user_audits():
    if not (current_user.is_admin or current_user.is_management or current_user.is_finance):
        flash("No tienes permisos para acceder a este módulo.", "danger")
        return redirect(url_for('security.login'))
    # 2. Pasamos el 'current_user' al servicio para evaluar su rol y sedes
    audits = AuditUserService.get_audit_history(current_user=current_user)
    
    return render_template('security/audit_user.html', audits=audits)