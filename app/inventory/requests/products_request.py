def validate_product_form(data):
    errors = {}

    name = data.get('name', '').strip()
    if not name:
        errors['name'] = 'Name is required.'

    sku = data.get('sku', '').strip()
    if not sku:
        errors['sku'] = 'SKU is required.'

    category_id = data.get('category_id')
    if not category_id or not str(category_id).isdigit():
        errors['category_id'] = 'Valid category is required.'

    unit_of_measure = data.get('unit_of_measure', '').strip()
    if not unit_of_measure:
        errors['unit_of_measure'] = 'Unit of measure is required.'

    quantity = data.get('quantity')
    if quantity and not str(quantity).replace('.', '', 1).isdigit():
        errors['quantity'] = 'Quantity must be a valid number.'
    elif not quantity:
        errors['quantity'] = 'Quantity is required.'

    technical_description = data.get('technical_description', '').strip()

    is_valid = len(errors) == 0

    validated_data = {
        'name': name,
        'sku': sku,
        'category_id': int(category_id) if category_id and str(category_id).isdigit() else None,
        'unit_of_measure': unit_of_measure,
        'technical_description': technical_description,
        'is_active': True
    }

    if quantity and str(quantity).replace('.', '', 1).isdigit():
        validated_data['quantity'] = float(quantity)

    return is_valid, errors, validated_data