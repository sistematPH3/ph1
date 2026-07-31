def validate_consumption_payload(data):
    errors = {}

    if 'product_id' not in data:
        errors['product_id'] = 'Required'
    elif not isinstance(data['product_id'], int) or data['product_id'] <= 0:
        errors['product_id'] = 'Must be a positive integer'

    if 'location_id' not in data:
        errors['location_id'] = 'Required'
    elif not isinstance(data['location_id'], int) or data['location_id'] <= 0:
        errors['location_id'] = 'Must be a positive integer'

    if 'quantity' not in data:
        errors['quantity'] = 'Required'
    elif not isinstance(data['quantity'], (int, float)) or data['quantity'] <= 0:
        errors['quantity'] = 'Must be a positive number'

    if 'notes' in data and not isinstance(data['notes'], str):
        errors['notes'] = 'Must be a string'
    elif 'notes' in data and len(data['notes']) > 255:
        errors['notes'] = 'Max length is 255'

    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }