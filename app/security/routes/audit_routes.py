from flask import Blueprint, render_template, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import LoginAudit

# Creamos el blueprint para la auditoría
audit_bp = Blueprint('audit', __name__, url_prefix='/auditoria')

@audit_bp.route('/accesos', methods=['GET'])
@login_required
def ver_auditoria_accesos():
    # 1. Obtenemos el rol del usuario actual de forma segura
    user_role = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    # 2. Restringimos el acceso: Solo los Jefes (Dirección) pueden ver esto
    roles_autorizados = ['Administrator', 'Manager', 'Assistant Manager']
    if user_role not in roles_autorizados:
        flash("No tienes permisos para acceder a este módulo.", "danger")
        return redirect(url_for('security.login')) # O la ruta de inicio común
    
    # 3. Consultamos todos los registros ordenados usando outerjoin
    # .outerjoin asegura que los usuarios sin sede (NULL) se incluyan en los resultados.
    historial = LoginAudit.query\
        .outerjoin(LoginAudit.location)\
        .order_by(LoginAudit.timestamp.desc())\
        .all()
    
    return render_template('security/login_audit.html', historial=historial)
