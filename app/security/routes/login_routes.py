from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .. import security_bp
from ..services.login_service import LoginService
from ..requests.auth_validators import mensaje_error_generico
from ..requests.login_validators import validar_formulario_login

# === IMPORTACIONES PARA LA AUDITORÍA ===
from app.extensions import db
from app.models import LoginAudit 
# =======================================

@security_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
      
        es_valido, datos = validar_formulario_login(request.form)
        
        if not es_valido:
            flash(mensaje_error_generico(), 'danger')
            return render_template('security/login.html')

        # El servicio retorna el usuario incluso si tiene sedes inactivas
        usuario = LoginService.autenticar(datos['email'], datos['password'])

        if usuario:
            # 1. Sincronización y refresco de estado (Ahora respeta al Guest con is_active=True)
            usuario.sync_activation_status()
            db.session.refresh(usuario)

            # 2. IDENTIFICACIÓN DE ROL DESDE EL MODELO
            es_invitado = usuario.is_guest

            # 3. VALIDACIÓN DE SEDES (SOLO SI NO ES INVITADO)
            if not es_invitado and not usuario.is_fully_active:
                flash("Actualmente no tienes sedes asignadas activas. Por favor, comunícate con el administrador.", "warning")
                return render_template('security/login.html')

            # 4. PROCEDER AL LOGIN ( Flask-Login ahora lo aceptará sin problemas )
            login_user(usuario)
            flash(f'Bienvenido al sistema PH, {usuario.name}', 'success')
            
            # 5. REGISTRO DE AUDITORÍA (Con control de seguridad para IndexError)
            sede_id = usuario.locations[0].id if (hasattr(usuario, 'locations') and usuario.locations) else None
            
            nuevo_ingreso = LoginAudit(
                user_id=usuario.id,
                location_id=sede_id,
                role_id=usuario.role_id,
                action='INICIO_SESION'
            )
            db.session.add(nuevo_ingreso)
            db.session.commit()

            # 6. REDIRECCIÓN SEGÚN ROL
            if usuario.is_admin:
                return redirect(url_for('security.admin_pending_requests'))
            
            elif usuario.is_management:
                return redirect(url_for('dashboard.director_dashboard'))
            
            # Prioridad máxima para invitados a la sala de espera
            elif es_invitado:
                return redirect(url_for('security.waiting_room'))
            
            return redirect(url_for('main.index'))
        
        # Si las credenciales fallan, mensaje genérico
        flash(mensaje_error_generico(), 'danger')

    return render_template('security/login.html')

@security_bp.route('/logout')
@login_required
def logout():
    # REGISTRO DE AUDITORÍA
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