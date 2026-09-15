import re
from datetime import datetime

FORMATOS_VALIDOS = ('pdf', 'excel')
SEVERIDADES_VALIDAS = ('NORMAL', 'ALERTA', 'CRITICO', 'EDITADO',
                       'ANULADO', 'REABASTECIDO')


def validate_audit_export_params(request_args):
    """Valida los parámetros comunes de las descargas de auditoría.

    Acepta: formato (pdf|excel), sede (id numérico, 'global' o nombre corto),
    rango de fechas desde/hasta (AAAA-MM-DD opcional), severidad (opcional),
    texto de búsqueda q (opcional) y hora exacta HH AM/PM (opcional).
    Devuelve: {'is_valid', 'data', 'errors'}.
    """
    errors = {}
    data = {'formato': 'pdf', 'sede': None, 'desde': None, 'hasta': None,
            'severity': None, 'q': None, 'hour': None, 'tab': None}

    formato = request_args.get('formato', 'pdf')
    if formato not in FORMATOS_VALIDOS:
        errors['formato'] = 'formato debe ser pdf o excel.'
    else:
        data['formato'] = formato

    sede = (request_args.get('sede') or '').strip()
    if sede:
        if sede.isdigit():
            data['sede'] = int(sede)
        elif sede.lower() == 'global':
            data['sede'] = 'global'
        elif len(sede) <= 100:
            data['sede'] = sede
        else:
            errors['sede'] = ('sede debe ser un id numérico, "global" '
                              'o un nombre de sede corto.')

    for campo, valor in (('desde', request_args.get('desde')),
                         ('hasta', request_args.get('hasta'))):
        if valor:
            try:
                data[campo] = datetime.strptime(valor, '%Y-%m-%d').date()
            except ValueError:
                errors[campo] = f'{campo} debe tener formato AAAA-MM-DD.'

    severity = request_args.get('severity')
    if severity:
        if severity in SEVERIDADES_VALIDAS:
            data['severity'] = severity
        else:
            errors['severity'] = ('severity debe ser NORMAL, ALERTA, CRITICO, '
                                  'EDITADO, ANULADO o REABASTECIDO.')

    tab = (request_args.get('tab') or '').strip()
    if tab:
        if tab in ('ingresos', 'egresos'):
            data['tab'] = tab
        else:
            errors['tab'] = 'tab debe ser ingresos o egresos.'

    q = (request_args.get('q') or '').strip()
    if q:
        data['q'] = q[:100]

    hour = (request_args.get('hour') or '').strip().upper()
    if hour:
        if re.fullmatch(r'(0[1-9]|1[0-2]) (AM|PM)', hour):
            data['hour'] = hour
        else:
            errors['hour'] = ('hour debe tener formato HH AM/PM '
                              '(ej. 07 AM, 12 PM, 01 PM).')

    return {'is_valid': not errors, 'data': data, 'errors': errors}
