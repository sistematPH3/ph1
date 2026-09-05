import math

def validate_register_waste_payload(data):
    errors = {}

    if 'location_id' not in data:
        errors['location_id'] = 'La sede es obligatoria.'
    elif not isinstance(data['location_id'], int) or data['location_id'] <= 0:
        errors['location_id'] = 'La sede es inválida.'

    if 'waste_type_id' not in data:
        errors['waste_type_id'] = 'El tipo de merma es obligatorio.'
    elif not isinstance(data['waste_type_id'], int) or data['waste_type_id'] <= 0:
        errors['waste_type_id'] = 'El tipo de merma es inválido.'

    if 'items' not in data:
        errors['items'] = 'Debe agregar al menos un producto a la merma.'
    elif not isinstance(data['items'], list) or len(data['items']) == 0:
        errors['items'] = 'Debe agregar al menos un producto a la merma.'
    else:
        for idx, item in enumerate(data['items']):
            if ('product_id' not in item or isinstance(item['product_id'], bool)
                    or not isinstance(item['product_id'], int) or item['product_id'] <= 0):
                errors[f'item_{idx}_product_id'] = 'Producto inválido.'

            if 'lot_number' not in item or not item['lot_number'] or not isinstance(item['lot_number'], str):
                errors[f'item_{idx}_lot_number'] = 'Debe seleccionar un lote para cada producto.'
            elif len(item['lot_number'].strip()) > 50:
                errors[f'item_{idx}_lot_number'] = 'El lote no puede exceder los 50 caracteres.'

            quantity = item.get('quantity')
            if ('quantity' not in item or isinstance(quantity, bool)
                    or not isinstance(quantity, (int, float))
                    or (isinstance(quantity, float) and not math.isfinite(quantity))):
                errors[f'item_{idx}_quantity'] = 'Cantidad inválida (debe ser mayor a 0).'
            elif quantity <= 0:
                errors[f'item_{idx}_quantity'] = 'Cantidad inválida (debe ser mayor a 0).'

    notes = data.get('notes')
    if notes is None or (isinstance(notes, str) and not notes.strip()):
        errors['notes'] = 'El motivo de la merma es obligatorio.'
    elif not isinstance(notes, str):
        errors['notes'] = 'El motivo debe ser un texto válido.'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }
