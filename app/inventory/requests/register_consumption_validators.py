def validate_consumption_payload(data):
    errors = {}

    if 'location_id' not in data:
        errors['location_id'] = 'Required'
    elif not isinstance(data['location_id'], int) or data['location_id'] <= 0:
        errors['location_id'] = 'Must be a positive integer'

    if 'items' not in data:
        errors['items'] = 'Required'
    elif not isinstance(data['items'], list) or len(data['items']) == 0:
        errors['items'] = 'Must be a non-empty array'
    else:
        for idx, item in enumerate(data['items']):
            if 'product_id' not in item or not isinstance(item['product_id'], int) or item['product_id'] <= 0:
                errors[f'item_{idx}_product_id'] = 'Invalid product'
            
            if 'quantity' not in item or not isinstance(item['quantity'], (int, float)) or item['quantity'] <= 0:
                errors[f'item_{idx}_quantity'] = 'Invalid quantity'

            if 'lot_number' in item and item['lot_number'] is not None and not isinstance(item['lot_number'], str):
                errors[f'item_{idx}_lot_number'] = 'Must be a string'
                
            if 'notes' in item and not isinstance(item['notes'], str):
                errors[f'item_{idx}_notes'] = 'Must be a string'
            elif 'notes' in item and len(item['notes']) > 255:
                errors[f'item_{idx}_notes'] = 'Max length is 255'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }