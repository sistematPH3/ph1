from flask import render_template, request, redirect, url_for, flash, jsonify
from .. import security_bp
from ..services.register_service import RegisterService
from ..repositories.register_repository import RegisterRepository

@security_bp.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json()
    email = data.get('email')
    
    existe = RegisterRepository.existe_usuario_por_email(email)
    
    return jsonify({"exists": existe})

@security_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
    
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        
        resultado = RegisterService.registrar_usuario(name, email, password)
        
        if resultado["success"]:
            flash(resultado["message"], 'success')
            return redirect(url_for('security.login')) 
        
        flash(resultado["message"], 'warning')
            
    return render_template('security/register.html')