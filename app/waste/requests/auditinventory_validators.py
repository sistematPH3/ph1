def validate_audit_filters(args):
    errors = {}
    
    # Validar location_id si se provee
    if 'location_id' in args and args['location_id']:
        try:
            location_id = int(args['location_id'])
            if location_id <= 0:
                errors['location_id'] = 'Debe ser un número entero positivo'
        except ValueError:
            errors['location_id'] = 'Formato de sede inválido'
            
    # Validar severity si se provee
    valid_severities = ['NORMAL', 'ALERTA', 'CRITICO', 'REABASTECIDO']
    if 'severity' in args and args['severity']:
        if args['severity'].upper() not in valid_severities:
            errors['severity'] = 'Nivel de severidad inválido'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }