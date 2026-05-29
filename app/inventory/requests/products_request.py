import re
from app.inventory.repositories.products_repository import ProductRepository

def validate_product_form(data, current_product_id=None):
    errors = {}

    name = data.get('name', '').strip()
    if not name:
        errors['name'] = 'El nombre del producto es obligatorio.'
    elif len(name) > 100:
        errors['name'] = 'El nombre no puede exceder los 100 caracteres.'

    raw_sku = data.get('sku', '').strip()
    cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper())
    
    if not cleaned_sku:
        errors['sku'] = 'El SKU es obligatorio.'
    elif len(cleaned_sku) > 50:
        errors['sku'] = 'El SKU no puede exceder los 50 caracteres.'
    else:
        existing_product = ProductRepository.find_by_sku(cleaned_sku)
        if existing_product and existing_product.id != current_product_id:
            errors['sku'] = f"El SKU '{cleaned_sku}' ya está registrado."

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
        elif len(unit_custom) > 20:
            errors['unit_of_measure'] = 'La unidad no puede exceder los 20 caracteres.'
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
        'sku': cleaned_sku,
        'category_id': int(category_id) if category_id and str(category_id).isdigit() else None,
        'unit_of_measure': unit_of_measure if is_valid else '',
        'quantity': int(quantity) if quantity and quantity.isdigit() else 0,
        'technical_description': technical_description,
        'is_active': True
    }

    return is_valid, errors, validated_data