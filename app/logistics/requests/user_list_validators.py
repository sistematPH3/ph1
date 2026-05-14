def validate_sede_assignment(data):
    errors = {}
    
    if not data:
        return {"payload": "No se enviaron datos para procesar."}
        
    if 'user_id' not in data:
        errors['user_id'] = 'El ID del usuario es requerido.'
    elif not isinstance(data['user_id'], int):
        errors['user_id'] = 'El ID del usuario debe ser un número entero.'
        
    if 'location_id' in data and data['location_id'] is not None:
        if not isinstance(data['location_id'], int):
            errors['location_id'] = 'El ID de la sede debe ser un número entero.'

    return errors