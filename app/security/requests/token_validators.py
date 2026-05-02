from app.security.requests.auth_validators import validar_credenciales_login

def validar_solicitud_recuperacion(data):
    """Valida que el correo exista y usa la validación del equipo para el formato."""
    if not data or not data.get('email'):
        return False, "El correo es obligatorio."
    
    email = data.get('email')
    
    if not validar_credenciales_login(email, "dummy123"):
        return False, "Por favor, ingrese un correo electrónico válido que contenga '@'."
        
    return True, None

def validar_nueva_password(data):
    """Usa la validación global del equipo para los límites de la contraseña."""
    if not data or not data.get('new_password'):
        return False, "La contraseña es obligatoria."
        
    nueva_password = data.get('new_password')
    
    if not validar_credenciales_login("correo@valido.com", nueva_password):
        return False, "La contraseña debe tener entre 6 y 12 caracteres."
        
    return True, None