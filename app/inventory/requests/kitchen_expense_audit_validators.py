from datetime import datetime

_VALID_SEVERITIES = ('NORMAL', 'ALERTA', 'CRITICO', 'EDITADO', 'ANULADO')


def validate_kitchen_expense_filters(request_args):
    """Parámetros del visor: sede, severidad, rango de fechas y pestaña."""
    filters = {}

    location_id = request_args.get('location_id')
    if location_id and location_id.isdigit():
        filters['location_id'] = int(location_id)

    severity = request_args.get('severity')
    if severity in _VALID_SEVERITIES:
        filters['severity'] = severity

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

    tab = request_args.get('tab') or 'gastos'
    filters['tab'] = tab if tab in ('gastos', 'ajustes') else 'gastos'
    return filters


def validate_kitchen_expense_action(data):
    """Contrato del endpoint de edición/anulación/activación (mismo estilo que
    el validador de AuditInventory)."""
    errors = {}

    if not data:
        return {'is_valid': False, 'errors': {'payload': 'No se enviaron datos.'}}

    log_id = data.get('log_id')
    if not log_id:
        errors['log_id'] = 'El ID del registro es obligatorio.'
    else:
        try:
            int(log_id)
        except (TypeError, ValueError):
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
            errors['new_quantity'] = 'Debe especificar la cantidad real gastada para editar el consumo.'
        else:
            try:
                new_qty_float = float(new_qty)
                if new_qty_float <= 0:
                    errors['new_quantity'] = 'La cantidad debe ser mayor a 0.'
                elif new_qty_float > 999999.99:
                    errors['new_quantity'] = 'La cantidad ingresada es excesiva (máx. 999999.99).'
            except (TypeError, ValueError):
                errors['new_quantity'] = 'La cantidad debe ser un valor numérico.'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
    }