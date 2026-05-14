def validate_sede_assignment(data):
    errors = {}
    
    if not data:
        return {"payload": "No se enviaron datos para procesar."}
        
    if 'user_id' not in data:
        errors['user_id'] = 'El ID del usuario es requerido.'
    elif not isinstance(data['user_id'], int):
        errors['user_id'] = 'El ID del usuario debe ser un número entero.'
        
    if 'location_ids' in data:
        if not isinstance(data['location_ids'], list):
            errors['location_ids'] = 'Las sedes deben enviarse en formato de lista.'
        else:
            for loc_id in data['location_ids']:
                if not isinstance(loc_id, int):
                    errors['location_ids'] = 'Todos los IDs de las sedes deben ser números enteros.'
                    break

    return errors