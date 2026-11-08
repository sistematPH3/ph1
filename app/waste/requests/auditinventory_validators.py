def validate_audit_filters(args):
    errors = {}
    
    if 'location_id' in args and args['location_id']:
        try:
            location_id = int(args['location_id'])
            if location_id <= 0:
                errors['location_id'] = 'Debe ser un número entero positivo'
        except ValueError:
            errors['location_id'] = 'Formato de sede inválido'
            
    valid_severities = ['NORMAL', 'ALERTA', 'CRITICO', 'REABASTECIDO', 'EDITADO', 'ANULADO']
    if 'severity' in args and args['severity']:
        if args['severity'].upper() not in valid_severities:
            errors['severity'] = 'Nivel de severidad inválido'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }

def validate_audit_action(data):
    errors = {}
    
    if not data:
        return {'is_valid': False, 'errors': {'payload': 'No se enviaron datos.'}}

    log_id = data.get('log_id')
    if not log_id:
        errors['log_id'] = 'El ID del registro es obligatorio.'
    else:
        try:
            int(log_id)
        except ValueError:
            errors['log_id'] = 'Formato de ID inválido.'

    action_type = data.get('action_type')
    if action_type not in ['EDITAR', 'ANULAR', 'ACTIVAR']:
        errors['action_type'] = 'Acción no permitida. Solo puede ser EDITAR, ANULAR o ACTIVAR.'

    notes = data.get('notes')
    if not notes or not str(notes).strip():
        errors['notes'] = 'Debe proporcionar un motivo obligatorio para realizar esta acción.'
        
    if action_type == 'EDITAR':
        new_qty = data.get('new_quantity')
        if new_qty is None or new_qty == '':
            errors['new_quantity'] = 'Debe especificar una nueva variación para procesar la edición.'
        else:
            try:
                float(new_qty)
            except (ValueError, TypeError):
                errors['new_quantity'] = 'La cantidad debe ser un valor numérico.'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }