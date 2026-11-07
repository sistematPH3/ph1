from flask import request, jsonify, render_template
from app.security import security_bp
from app.security.services.token_services import solicitar_recuperacion, cambiar_password, verificar_vigencia_token
from app.security.requests.token_validators import validar_solicitud_recuperacion, validar_nueva_password


@security_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('security/token_forgot.html')
        
    data = request.get_json()
    
    es_valido, mensaje_error = validar_solicitud_recuperacion(data)
    if not es_valido:
        return jsonify({"error": mensaje_error}), 400
        
    email = data.get('email')
    exito = solicitar_recuperacion(email)
    
    if exito:
        return jsonify({"message": "Correo comprobado, recibirás un enlace al correo con las siguientes instrucciones que debes seguir."}), 200
    else:
        return jsonify({"error": "El correo ingresado no existe en el sistema."}), 404


@security_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if request.method == 'GET':
        
        es_valido = verificar_vigencia_token(token)
        
        return render_template('security/token_reset.html', token=token, token_valido=es_valido)
        
    data = request.get_json()
    
    es_valido, mensaje_error = validar_nueva_password(data)
    if not es_valido:
        return jsonify({"error": mensaje_error}), 400
        
    nueva_password = data.get('new_password')
    exito = cambiar_password(token, nueva_password)
    
    if exito:
        return jsonify({"message": "Tu contraseña ha sido actualizada con éxito. Ya puedes iniciar sesión."}), 200
    else:
        return jsonify({"error": "El enlace de recuperación es inválido o ha expirado."}), 400