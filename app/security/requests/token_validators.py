from app.security.requests.auth_validators import validar_email, validar_password


def validar_solicitud_recuperacion(data):
    """
    Valida el formato del correo de la peticion de recuperacion.

    No consulta la base de datos a proposito: la respuesta debe ser identica
    exista o no el usuario, para no permitir enumerar cuentas.
    """
    if not data or not data.get('email'):
        return False, "El correo es obligatorio."

    if not validar_email(data.get('email')):
        return False, "Por favor, ingrese un correo electrónico válido."

    return True, None


def validar_nueva_password(data):
    """Aplica las reglas globales de contrasena al nuevo valor."""
    if not data or not data.get('new_password'):
        return False, "La contraseña es obligatoria."

    es_valida, mensaje_error = validar_password(data.get('new_password'))
    if not es_valida:
        return False, mensaje_error

    return True, None
