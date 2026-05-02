from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user
from .. import security_bp
#from . import user_management_routes 
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
        
        usuario = LoginService.autenticar(datos['email'], datos['password'])

        if usuario:
            login_user(usuario)

            flash(f'Bienvenido al sistema PH, {usuario.name}', 'success')
            

            roles_jefes = ['Administrator', 'Manager', 'Assistant Manager']
            user_role = usuario.role.name if hasattr(usuario.role, 'name') else usuario.role

            if user_role in roles_jefes:
                return redirect(url_for('security.admin_pending_requests'))
            
            return redirect(url_for('main.index'))
        
        flash(mensaje_error_generico(), 'danger')

    return render_template('security/login.html')
            
    return render_template('security/login.html')