from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user
from .. import security_bp
from . import user_management_routes 
from ..services.login_service import LoginService
# Importamos lo compartido y el nuevo validador específico para Login
from ..requests.auth_validators import mensaje_error_generico
from ..requests.login_validators import validar_formulario_login

@security_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
      
        es_valido, datos = validar_formulario_login(request.form)
        
        if not es_valido:
    
            flash(mensaje_error_generico(), 'danger')
            return render_template('security/login.html')

  
        usuario = LoginService.autenticar(datos['email'], datos['password'])

        if usuario:
            login_user(usuario)
            flash(f'Bienvenido al sistema PH, {usuario.name}', 'success')
            
            # Obtenemos el nombre del rol
            user_role = usuario.role.name if hasattr(usuario.role, 'name') else usuario.role

            # 1. Si es Jefe, va al panel de aprobación
            roles_jefes = ['Administrator', 'Manager', 'Assistant Manager']
            if user_role in roles_jefes:
                return redirect(url_for('security.admin_pending_requests'))
            
            # 2. Si es Invitado (nuevo), va a la pantalla del perrito
            if user_role == 'Guest':
                return redirect(url_for('security.waiting_room'))
            
            # 3. Si es cualquier otro rol, va al inicio normal
            return redirect(url_for('main.index'))
        
        # Si las credenciales fallan (usuario es None)
        flash(mensaje_error_generico(), 'danger')

    return render_template('security/login.html')
            
@security_bp.route('/waiting-room')
def waiting_room():
 return render_template('security/waiting_room.html')
