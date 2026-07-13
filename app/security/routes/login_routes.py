from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .. import security_bp
from ..services.login_service import LoginService
from ..requests.auth_validators import mensaje_error_generico
from ..requests.login_validators import validar_formulario_login
from app.extensions import db
from app.models import LoginAudit 

@security_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        es_valido, datos = validar_formulario_login(request.form)
        
        if not es_valido:
            flash(mensaje_error_generico(), 'danger')
            return render_template('security/login.html')

        usuario, estado = LoginService.autenticar(datos['email'], datos['password'])

        if estado == "ok":
            login_user(usuario)
            flash(f'Bienvenido al sistema PH, {usuario.name}', 'success')
            
            sede_id = usuario.locations[0].id if (hasattr(usuario, 'locations') and usuario.locations) else None
            nuevo_ingreso = LoginAudit(
                user_id=usuario.id,
                location_id=sede_id,
                role_id=usuario.role_id,
                action='INICIO_SESION'
            )
            db.session.add(nuevo_ingreso)
            db.session.commit()

            if usuario.is_admin:
                return redirect(url_for('dashboard.admin_dashboard'))
            elif usuario.is_management:
                return redirect(url_for('dashboard.director_dashboard'))
            elif getattr(usuario, 'is_manager', False) or usuario.role_id == 2:
                return redirect(url_for('dashboard.manager_dashboard'))
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
    sede_id = current_user.locations[0].id if (hasattr(current_user, 'locations') and current_user.locations) else None
        
    cierre_sesion = LoginAudit(
        user_id=current_user.id,
        location_id=sede_id,
        role_id=current_user.role_id,
        action='CERRAR_SESION'
    )
    db.session.add(cierre_sesion)
    db.session.commit()
    
    logout_user()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('security.login'))
            
@security_bp.route('/waiting-room')
@login_required
def waiting_room():
    return render_template('security/waiting_room.html')