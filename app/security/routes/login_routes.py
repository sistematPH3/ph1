from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_user, logout_user, login_required, current_user
from .. import security_bp
from ..services.login_service import LoginService
from ..requests.auth_validators import mensaje_error_generico
from ..requests.login_validators import validar_formulario_login
from app.extensions import db
from app.models import LoginAudit


def _registrar_acceso(usuario, accion):
    """Registra el acceso en la auditoría sin bloquear la sesión.

    Si la escritura del log falla (por ejemplo, una validación o un problema
    de base de datos), se revierte solo esa transacción y se registra el
    error técnico. El usuario ya autenticado no debe perder su sesión por un
    fallo de auditoría.
    """
    try:
        sede_id = (usuario.locations[0].id
                   if getattr(usuario, 'locations', None) else None)
        db.session.add(LoginAudit(
            user_id=usuario.id,
            location_id=sede_id,
            role_id=usuario.role_id,
            action=accion,
        ))
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "No se pudo registrar el acceso %s del usuario %s",
            accion,
            getattr(usuario, 'id', '?'),
        )
        return False

@security_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        es_valido, datos = validar_formulario_login(request.form)
        
        if not es_valido:
            flash(mensaje_error_generico(), 'danger')
            return render_template('security/login.html')

        usuario, estado = LoginService.autenticar(datos['email'], datos['password'])

        if estado == "ok":
            # El invitado pendiente tiene is_active=False; sin force, Flask-Login
            # no crea la sesión y nunca llegaría a la sala de espera.
            login_user(usuario, force=usuario.is_guest)
            _registrar_acceso(usuario, 'INICIO_SESION')

            if usuario.is_admin:
                return redirect(url_for('dashboard.admin_dashboard'))
            elif usuario.is_management:
                return redirect(url_for('dashboard.director_dashboard'))
            elif getattr(usuario, 'is_manager', False) or usuario.role_id == 2:
                return redirect(url_for('dashboard.manager_dashboard'))
            elif getattr(usuario, 'is_finance', False):
                return redirect(url_for('dashboard.finance_dashboard'))
            elif getattr(usuario, 'is_operations', False) or usuario.role_id == 4:
                return redirect(url_for('dashboard.operations_dashboard'))
            elif getattr(usuario, 'is_assistant_manager', False):
                return redirect(url_for('dashboard.assistant_manager_dashboard'))
            elif usuario.is_guest:
                return redirect(url_for('security.waiting_room'))
            else:
                return redirect(url_for('security.login'))

        elif estado == "cuenta_desactivada":
            flash("Actualmente su cuenta está fuera de servicio, comuníquese con el administrador.", "warning")
        
        elif estado == "sin_sedes":
            flash("No puedes entrar al sistema porque no tienes sedes activas, comunícate con el administrador.", "warning")
            
        else:
            flash(mensaje_error_generico(), 'danger')

    return render_template('security/login.html')

@security_bp.route('/logout')
@login_required
def logout():
    _registrar_acceso(current_user, 'CERRAR_SESION')
    logout_user()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('security.login'))
            
@security_bp.route('/waiting-room')
@login_required
def waiting_room():
    return render_template('security/waiting_room.html')