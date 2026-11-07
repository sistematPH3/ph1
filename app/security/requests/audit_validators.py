from datetime import datetime

def validar_id_entidad(campo_nombre, valor, obligatorio=True):
    """
    Valida que los IDs (user_id, role_id, location_id) sean enteros no negativos.
    Permite el 0 porque se usa como valor por defecto para roles o estados iniciales.
    """
    if valor is None:
        if obligatorio:
            raise ValueError(f"El campo '{campo_nombre}' es obligatorio.")
        return None
        
    # Cambiamos '<= 0' por '< 0' para permitir que el 0 sea un rol válido (como el de tus invitados)
    if not isinstance(valor, int) or valor < 0:
        raise ValueError(f"El campo '{campo_nombre}' debe ser un número entero mayor o igual a cero.")
    return valor

def validar_accion_auditoria(accion):
    """
    Valida que la acción no esté vacía y no supere los 50 caracteres (character varying(50)).
    """
    if not accion or not isinstance(accion, str):
        raise ValueError("La acción registrada no puede estar vacía.")
        
    accion_limpia = accion.strip()
    
    if len(accion_limpia) > 50:
        raise ValueError("La acción no puede superar los 50 caracteres.")
        
    return accion_limpia

def validar_timestamp_auditoria(timestamp):
    """
    Asegura que el timestamp sea un objeto datetime válido y no esté en el futuro.
    """
    if timestamp is None:
        return datetime.utcnow()
        
    if not isinstance(timestamp, datetime):
        raise ValueError("El timestamp debe ser una fecha/hora válida.")
        
    if timestamp > datetime.utcnow():
        raise ValueError("No se pueden registrar eventos con fechas futuras.")
        
    return timestamp