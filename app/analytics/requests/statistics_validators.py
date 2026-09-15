"""Validadores del cajón de estadísticas (Rápido 1 - Módulo 8).

Centraliza la validación de lo que entra por HTTP antes de que llegue al
servicio, siguiendo el patrón del resto del proyecto (app.<modulo>.requests).
"""
from decimal import Decimal, InvalidOperation

PERIOD_TYPES = ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUAL')
MONEDAS = ('USD', 'EUR', 'BS')


def validate_period_type(value, default='WEEKLY'):
    """Devuelve el tipo de período normalizado o el `default`.

    La vista arranca en WEEKSemanal (la unidad mínima) y los demás se
    despliegan después; si el envío es inválido se usa WEEKLY.
    """
    raw = str(value or default).upper()
    return raw if raw in PERIOD_TYPES else default


def validate_moneda(value, default='USD'):
    raw = str(value or default).upper()
    return raw if raw in MONEDAS else default


def validate_refresh_payload(data):
    """Valida el cuerpo de POST /estadisticas/refresh.

    Devuelve {is_valid: True, period_type} o {is_valid: False, errors}.
    """
    if not data or not isinstance(data, dict):
        return {'is_valid': False,
                'errors': {'period_type': 'El cuerpo de la solicitud no es válido.'}}
    periodo = str(data.get('period_type') or 'WEEKLY').upper()
    if periodo not in PERIOD_TYPES:
        return {
            'is_valid': False,
            'errors': {'period_type': f"Tipo de período no válido: {periodo}."},
        }
    return {'is_valid': True, 'period_type': periodo}


def validate_config_payload(data):
    """Valida factor y mínimo absoluto de las alarmas y la moneda por defecto.

    Devuelve {is_valid: True, factor, minimo_usd, moneda}
    o {is_valid: False, errors}.
    """
    if not data or not isinstance(data, dict):
        return {'is_valid': False,
                'errors': {'general': 'El cuerpo de la solicitud no es válido.'}}

    errors = {}
    try:
        factor = Decimal(str(data.get('ESTADISTICAS_FACTOR', '')))
        if factor <= 0:
            errors['ESTADISTICAS_FACTOR'] = 'Debe ser un número mayor que 0.'
    except (InvalidOperation, ValueError, TypeError):
        errors['ESTADISTICAS_FACTOR'] = 'Valor numérico no válido.'

    try:
        minimo = Decimal(str(data.get('ESTADISTICAS_MINIMO_USD', '')))
        if minimo < 0:
            errors['ESTADISTICAS_MINIMO_USD'] = 'Debe ser un número mayor o igual que 0.'
    except (InvalidOperation, ValueError, TypeError):
        errors['ESTADISTICAS_MINIMO_USD'] = 'Valor numérico no válido.'

    moneda = str(data.get('ESTADISTICAS_MONEDA') or 'USD').upper()
    if moneda not in MONEDAS:
        errors['ESTADISTICAS_MONEDA'] = f"Moneda no válida: {moneda}. Use USD, EUR o BS."

    if errors:
        return {'is_valid': False, 'errors': errors}

    return {
        'is_valid': True,
        'factor': str(data.get('ESTADISTICAS_FACTOR')),
        'minimo_usd': str(data.get('ESTADISTICAS_MINIMO_USD')),
        'moneda': moneda,
    }