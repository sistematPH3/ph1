"""Validadores de la bandeja de aprobación de mermas.

Validan el payload recibido en las acciones de aprobar/rechazar una merma
pendiente. Mismo patrón que register_consumption_validators.
"""


def validate_resolution_payload(data, action):
    """Valida el payload para aprobar (approve), rechazar (reject) o cancelar (cancel) una merma.

    data: dict del cuerpo de la petición.
    action: 'approve' | 'reject' | 'cancel'
    """
    errors = {}

    if action == 'reject':
        reason = (data.get('reason') or '').strip()
        if not reason:
            errors['reason'] = 'El motivo de rechazo es obligatorio.'
        elif len(reason) < 15:
            errors['reason'] = 'El motivo de rechazo debe tener al menos 15 caracteres.'

    if action == 'cancel':
        reason = (data.get('reason') or '').strip()
        if not reason:
            errors['reason'] = 'El motivo de cancelación es obligatorio.'
        elif len(reason) < 10:
            errors['reason'] = 'El motivo de cancelación debe tener al menos 10 caracteres.'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
    }
