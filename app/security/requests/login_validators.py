# app/security/requests/login_validators.py

def validar_formulario_login(form):
    """
    Verifica que los campos de login existan y cumplan con el formato básico.
    Retorna (True, datos_limpios) o (False, None)
    """
    email = form.get('email', '').strip()
    password = form.get('password', '')

    # Validaciones básicas de presencia
    if not email or not password:
        return False, None

    

    # Retornamos los datos limpios (email en minúsculas, sin espacios)
    return True, {
        "email": email.lower(),
        "password": password
    }