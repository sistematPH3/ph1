from flask import Blueprint, render_template, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import LoginAudit, Location, Role 
from sqlalchemy.orm import joinedload

audit_bp = Blueprint('audit', __name__, url_prefix='/auditoria')

@audit_bp.route('/accesos', methods=['GET'])
@login_required
def ver_auditoria_accesos():
    user_role = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    roles_autorizados = ['Administrator', 'Finance']
    if user_role not in roles_autorizados:
        flash("No tienes permisos para acceder a este módulo.", "danger")
        return redirect(url_for('security.login'))
    
    # 1. Iniciamos la consulta base
    query = LoginAudit.query.options(
        joinedload(LoginAudit.user),
        joinedload(LoginAudit.role),
        joinedload(LoginAudit.location)
    )
    
    # 2. Aplicamos las reglas de negocio si el usuario es de Finanzas
    if user_role == 'Finance':
        # SOLUCIÓN: Extraemos los IDs de las sedes (locations) del usuario actual
        user_location_ids = [loc.id for loc in current_user.locations]
        
        # Filtramos para que vea los registros que coincidan con sus sedes
        query = query.filter(LoginAudit.location_id.in_(user_location_ids))
        
        # Excluimos los roles Administrator y Guest 
        query = query.join(LoginAudit.role).filter(
            Role.name.notin_(['Administrator', 'Guest'])
        )
        
    # 3. Finalizamos construyendo el ordenamiento y ejecutando la consulta
    historial = query.order_by(LoginAudit.timestamp.desc()).all()
        
    sedes = Location.query.order_by(Location.name.asc()).all()
    
    return render_template('security/login_audit.html', historial=historial, sedes=sedes)