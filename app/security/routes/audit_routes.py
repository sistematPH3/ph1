from flask import Blueprint, render_template, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import LoginAudit, Location
from sqlalchemy.orm import joinedload

audit_bp = Blueprint('audit', __name__, url_prefix='/auditoria')

@audit_bp.route('/accesos', methods=['GET'])
@login_required
def ver_auditoria_accesos():
    user_role = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    roles_autorizados = ['Administrator', 'Manager', 'Assistant Manager']
    if user_role not in roles_autorizados:
        flash("No tienes permisos para acceder a este módulo.", "danger")
        return redirect(url_for('security.login'))
    
    historial = LoginAudit.query\
        .options(
            joinedload(LoginAudit.user),
            joinedload(LoginAudit.role),
            joinedload(LoginAudit.location)
        )\
        .order_by(LoginAudit.timestamp.desc())\
        .all()
        
    sedes = Location.query.order_by(Location.name.asc()).all()
    
    return render_template('security/login_audit.html', historial=historial, sedes=sedes)