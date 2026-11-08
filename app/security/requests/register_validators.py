from ..requests.auth_validators import validar_email, validar_password
from ..repositories.register_repository import RegisterRepository

LIMITE_NOMBRE = 40


def validar_nombre_registro(name):
    """El nombre es obligatorio y tiene un tope de longitud."""
    if not name or not str(name).strip():
        return False, "Por favor, ingrese su nombre."

    if len(name.strip()) > LIMITE_NOMBRE:
        return False, f"El nombre no puede exceder los {LIMITE_NOMBRE} caracteres."

    return True, ""


def validar_datos_registro(name, email, password):
    """
    Valida nombre, correo y contrasena en un solo lugar.

    Devuelve (valido, mensaje). Antes devolvia un dict y el servicio descartaba
    el mensaje concreto para responder siempre 'Este usuario ya existe',
    aunque el fallo hubiera sido el nombre o la contrasena.
    """
    es_valido, mensaje = validar_nombre_registro(name)
    if not es_valido:
        return False, mensaje

    if not validar_email(email):
        return False, "Por favor, verifique el formato del correo."

    es_valido, mensaje = validar_password(password)
    if not es_valido:
        return False, mensaje

    # Se consulta con el correo ya recortado: si se buscara en crudo, alguien
    # que escribiera '  correo@mail.com  ' no coincidiria con el registro
    # existente y la insercion reventaria contra la restriccion de unicidad.
    if RegisterRepository.existe_usuario_por_email(email.strip()):
        return False, "Este correo ya está registrado."

    return True, ""
