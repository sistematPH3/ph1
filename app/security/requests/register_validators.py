from ..repositories.register_repository import RegisterRepository

def validar_datos_registro(name, email):
    """
    Validaciones específicas de Diego.
    """
    
    if len(name) > 40:
        return {"valido": False, "mensaje": "El nombre de usuario no puede exceder los 40 caracteres."}
    
    
    if RegisterRepository.existe_usuario_por_email(email):
        return {"valido": False, "mensaje": "Este correo ya está registrado."}
    
    return {"valido": True}