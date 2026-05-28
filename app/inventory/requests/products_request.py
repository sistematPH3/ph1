def validate_product_form(data):
    errors = {}

    name = data.get('name', '').strip()
    if not name:
        errors['name'] = 'El nombre del producto es obligatorio.'

    sku = data.get('sku', '').strip()
    if not sku:
        errors['sku'] = 'El SKU es obligatorio.'

    category_id = data.get('category_id')
    if not category_id or not str(category_id).isdigit():
        errors['category_id'] = 'Debe seleccionar una categoría válida.'

    unit_select = data.get('unit_of_measure_select', '')
    unit_custom = data.get('unit_of_measure_custom', '').strip()

    if not unit_select:
        errors['unit_of_measure'] = 'La unidad de medida es obligatoria.'
    elif unit_select == 'OTHER':
        if not unit_custom:
            errors['unit_of_measure'] = 'Debe especificar la nueva unidad de medida.'
        else:
            unit_of_measure = unit_custom
    else:
        unit_of_measure = unit_select

    quantity = data.get('quantity', '').strip()
    if not quantity or not quantity.isdigit():
        errors['quantity'] = 'La cantidad debe ser un número entero válido.'

    technical_description = data.get('technical_description', '').strip()

    is_valid = len(errors) == 0

    validated_data = {
        'name': name,
        'sku': sku,
        'category_id': int(category_id) if category_id and str(category_id).isdigit() else None,
        'unit_of_measure': unit_of_measure if is_valid else '',
        'quantity': int(quantity) if quantity and quantity.isdigit() else 0,
        'technical_description': technical_description,
        'is_active': True
    }

    return is_valid, errors, validated_data