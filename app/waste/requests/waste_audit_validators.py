from datetime import datetime

def validate_audit_filters(args):
    """Valida los parámetros de búsqueda del historial de auditoría de mermas."""
    errors = []
    start_date = args.get('start_date')
    end_date = args.get('end_date')
    severity = args.get('severity')
    
    if start_date:
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            errors.append("El formato de fecha de inicio debe ser YYYY-MM-DD.")
            
    if end_date:
        try:
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            errors.append("El formato de fecha de fin debe ser YYYY-MM-DD.")
            
    if severity and severity not in ['NORMAL', 'ALERTA', 'CRITICO']:
        errors.append("La gravedad especificada no es válida.")
        
    return errors