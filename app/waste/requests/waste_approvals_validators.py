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


def validate_lines_decision_payload(data):
    """Valida el payload de decisión POR PRODUCTO.

    data: dict con 'decisiones' = lista de {detail_id, decision, reason?}.
    decision: 'aprobar' | 'rechazar'. Si es 'rechazar', el motivo es obligatorio
    (mín. 15 caracteres) por cada producto rechazado.
    """
    errors = {}
    decisiones = data.get('decisiones')

    if not isinstance(decisiones, list) or not decisiones:
        errors['decisiones'] = 'Debe enviar al menos una línea por decidir.'
        return {'is_valid': False, 'errors': errors}

    for i, dec in enumerate(decisiones):
        prefijo = f'decisiones.{i}'
        if not isinstance(dec, dict):
            errors[prefijo] = 'Línea de decisión inválida.'
            continue

        detail_id = dec.get('detail_id')
        try:
            int(detail_id)
        except (TypeError, ValueError):
            errors[f'{prefijo}.detail_id'] = 'El detail_id de la línea es obligatorio.'

        decision = str(dec.get('decision') or '').strip()
        if decision not in ('aprobar', 'rechazar'):
            errors[f'{prefijo}.decision'] = "La decisión debe ser 'aprobar' o 'rechazar'."

        if decision == 'rechazar':
            reason = str(dec.get('reason') or '').strip()
            if not reason:
                errors[f'{prefijo}.reason'] = 'El motivo de rechazo de este producto es obligatorio.'
            elif len(reason) < 15:
                errors[f'{prefijo}.reason'] = 'El motivo de rechazo debe tener al menos 15 caracteres.'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
    }
