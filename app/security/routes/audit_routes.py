from flask import Blueprint, render_template, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import LoginAudit
from sqlalchemy.orm import joinedload

# Creamos el blueprint para la auditoría
audit_bp = Blueprint('audit', __name__, url_prefix='/auditoria')

@audit_bp.route('/accesos', methods=['GET'])
@login_required
def ver_auditoria_accesos():
    # 1. Obtenemos el rol del usuario actual de forma segura
    user_role = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    # 2. Restringimos el acceso
    roles_autorizados = ['Administrator', 'Manager', 'Assistant Manager']
    if user_role not in roles_autorizados:
        flash("No tienes permisos para acceder a este módulo.", "danger")
        return redirect(url_for('security.login'))
    
    # 3. CONSULTA FORZADA Y OPTIMIZADA
    # Eliminamos filtros restrictivos para ver qué hay realmente en la tabla
    historial = LoginAudit.query\
        .options(
            joinedload(LoginAudit.user),
            joinedload(LoginAudit.role),
            joinedload(LoginAudit.location)
        )\
        .order_by(LoginAudit.timestamp.desc())\
        .all()
    
    # --- BLOQUE DE DIAGNÓSTICO ---
    # Esto imprimirá en la consola de tu terminal los datos reales que Flask está obteniendo.
    # Si ves registros aquí pero no en la web, el problema es el HTML.
    # Si ves fechas como "None" o años incorrectos aquí, el problema es el guardado en la BD.
    print(f"--- DIAGNÓSTICO DE AUDITORÍA: Se encontraron {len(historial)} registros ---")
    for log in historial[:5]: # Imprimimos los 5 más recientes
        print(f"ID: {log.id} | Acción: {log.action} | Timestamp: {log.timestamp} | Tipo: {type(log.timestamp)}")
    # -----------------------------
    
    return render_template('security/login_audit.html', historial=historial)