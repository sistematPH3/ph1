import re

def validar_credenciales_login(email, password):
    """
    Retorna True si el formato es válido, de lo contrario False.
    """
    # 1. Validar presencia de @
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return False
    
    # Validar longitud mínima de contraseña (mínimo 6)
    if len(password) < 6:
        return False

    # Validar longitud máxima de contraseña (máximo 12)
    if len(password) > 12:
        return False
        
    return True

def mensaje_error_generico():
    return "Los datos ingresados son erróneos. Por favor, intente de nuevo."