# app/logistics/requests/movement_audit_validators.py
from datetime import datetime

def validate_audit_filters(request_args):
    """
    Validación de parámetros de búsqueda: rango de fechas, location_id y severity.
    """
    filters = {}
    
    # Validar location_id
    location_id = request_args.get('location_id')
    if location_id and location_id.isdigit():
        filters['location_id'] = int(location_id)

    # Validar severity
    severity = request_args.get('severity')
    if severity in ['NORMAL', 'ALERTA', 'CRITICO']:
        filters['severity'] = severity

    # Validar fechas (start_date y end_date)
    start_date = request_args.get('start_date')
    end_date = request_args.get('end_date')
    
    if start_date:
        try:
            filters['start_date'] = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            pass 

    if end_date:
        try:
            filters['end_date'] = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            pass

    return filters