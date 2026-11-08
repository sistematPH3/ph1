from datetime import datetime, timezone, timedelta

def validar_id_entidad(campo_nombre, valor, obligatorio=True):
    """
    Valida que los IDs (user_id, role_id, location_id) sean enteros no negativos.
    """
    if valor is None:
        if obligatorio:
            raise ValueError(f"El campo '{campo_nombre}' es obligatorio.")
        return None
        
    if not isinstance(valor, int) or valor < 0:
        raise ValueError(f"El campo '{campo_nombre}' debe ser un número entero mayor o igual a cero.")
    return valor

def validar_accion_auditoria(accion):
    """
    Valida que la acción no esté vacía y no supere los 50 caracteres.
    """
    if not accion or not isinstance(accion, str):
        raise ValueError("La acción registrada no puede estar vacía.")
        
    accion_limpia = accion.strip()
    
    if len(accion_limpia) > 50:
        raise ValueError("La acción no puede superar los 50 caracteres.")
        
    return accion_limpia

def validar_timestamp_auditoria(timestamp):
    """
    Asegura que el timestamp sea válido, ajustado a hora Venezuela (UTC-4),
    y permite un margen de tolerancia para evitar rechazos por milisegundos.
    """
    # 1. Definir el huso horario de Venezuela
    tz_venezuela = timezone(timedelta(hours=-4))
    
    # 2. Obtener hora actual de Venezuela (naive)
    hora_actual_venezuela = datetime.now(tz_venezuela).replace(tzinfo=None)

    # 3. Si no hay timestamp, asignar la hora actual inmediatamente
    if timestamp is None:
        return hora_actual_venezuela
        
    if not isinstance(timestamp, datetime):
        raise ValueError("El timestamp debe ser una fecha/hora válida.")
        
    # 4. Normalizar zona horaria del timestamp recibido
    if timestamp.tzinfo is not None:
        timestamp_comparar = timestamp.astimezone(tz_venezuela).replace(tzinfo=None)
    else:
        timestamp_comparar = timestamp

    # 5. AJUSTE: Tolerancia de 2 minutos
    # Esto soluciona el problema de registros rechazados por desfases mínimos
    # entre el servidor y el tiempo de inserción.
    tolerancia = timedelta(minutes=2)
    
    # Validamos que el evento no sea una fecha futura (con margen)
    if timestamp_comparar > (hora_actual_venezuela + tolerancia):
        # Aquí puedes decidir si prefieres "corregirlo" automáticamente 
        # o lanzar el error. Para auditoría, es mejor corregir al presente:
        return hora_actual_venezuela
        
    return timestamp_comparar