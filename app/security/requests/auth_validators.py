import re


# --- Reglas de contraseña: fuente única de verdad -------------------------
# El frontend las lee de data-* en la plantilla, por lo que no se duplican.
REGLAS_PASSWORD = {
    'min_length': 6,
    'max_length': 12,
    'require_upper': True,
    'require_special': True,
}

# Anclada con fullmatch: 'a@b.com basura' ya no es un correo valido.
PATRON_EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")

PATRON_ESPECIAL = re.compile(r"[^A-Za-z0-9]")
PATRON_MAYUSCULA = re.compile(r"[A-Z]")


def validar_email(email):
    """True si el correo tiene un formato válido. No revela si el usuario existe."""
    if not email or not isinstance(email, str):
        return False
    return PATRON_EMAIL.fullmatch(email.strip()) is not None


def validar_password(password):
    """Aplica REGLAS_PASSWORD. Devuelve (es_valida, mensaje_error)."""
    if not password or not isinstance(password, str):
        return False, "La contraseña es obligatoria."

    minimo = REGLAS_PASSWORD['min_length']
    maximo = REGLAS_PASSWORD['max_length']

    if len(password) < minimo or len(password) > maximo:
        return False, f"La contraseña debe tener entre {minimo} y {maximo} caracteres."

    if REGLAS_PASSWORD['require_special'] and not PATRON_ESPECIAL.search(password):
        return False, "Esta contraseña debe incluir caracteres especiales."

    if REGLAS_PASSWORD['require_upper'] and not PATRON_MAYUSCULA.search(password):
        return False, "Esta contraseña debe incluir al menos una letra mayúscula."

    return True, None


def validar_credenciales_login(email, password):
    """
    Retorna True si el formato de email y la contrasena son validos.
    Se mantiene para no romper el login y el registro existentes.
    """
    if not validar_email(email):
        return False
    return validar_password(password)[0]


def mensaje_error_generico():
    return "Los datos ingresados son erróneos. Por favor, intente de nuevo."
