from datetime import datetime

VALID_METRICS = ('PURCHASES', 'KITCHEN_CONSUMPTION', 'WASTE', 'TRANSFERS',
                 'CONSOLIDATED')
VALID_PERIOD_TYPES = ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUAL')
VALID_CURRENCIES = ('USD', 'BS', 'EUR')


def validate_report_filters(data):
    """Normaliza y valida los filtros comunes de los reportes de estadística."""
    errors = {}

    metric = (data.get('metric') or 'PURCHASES').upper()
    if metric not in VALID_METRICS:
        errors['metric'] = 'Invalid metric'
    data['metric'] = metric

    period_type = (data.get('period_type') or 'MONTHLY').upper()
    if period_type not in VALID_PERIOD_TYPES:
        errors['period_type'] = 'Invalid period type'
    data['period_type'] = period_type

    moneda = (data.get('moneda') or 'USD').upper()
    if moneda not in VALID_CURRENCIES:
        errors['moneda'] = 'Invalid currency'
    data['moneda'] = moneda

    location_id = data.get('location_id')
    if location_id is not None and location_id != '':
        try:
            location_id = int(location_id)
        except (TypeError, ValueError):
            errors['location_id'] = 'Must be an integer'
        else:
            if location_id <= 0:
                errors['location_id'] = 'Must be a positive integer'
    else:
        location_id = None
    data['location_id'] = location_id

    period_start = data.get('period_start')
    if period_start:
        try:
            data['period_start'] = datetime.strptime(
                str(period_start), '%Y-%m-%d').date()
        except ValueError:
            errors['period_start'] = 'Invalid date (expected YYYY-MM-DD)'
    else:
        data['period_start'] = None

    def _parsear_dia(campo):
        valor = data.get(campo)
        if not valor:
            return None
        try:
            return datetime.strptime(str(valor), '%Y-%m-%d').date()
        except ValueError:
            errors[campo] = 'Invalid date (expected YYYY-MM-DD)'
            return None

    data['desde'] = _parsear_dia('desde')
    data['hasta'] = _parsear_dia('hasta')
    if data['desde'] and data['hasta'] and data['desde'] > data['hasta']:
        errors['desde'] = 'from must be before or equal to to'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'data': data,
    }