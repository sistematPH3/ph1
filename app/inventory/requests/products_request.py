import re
from datetime import date
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

    product_type_id = data.get('product_type_id')
    if not product_type_id or not str(product_type_id).isdigit():
        errors['product_type_id'] = 'Debe seleccionar un tipo de producto válido.'

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


    technical_description = data.get('technical_description', '').strip()

    # NUEVA VALIDACIÓN: Procesar los cuadritos de fecha de manera unificada
    day = data.get('date_day')
    month = data.get('date_month')
    year = data.get('date_year')

    expiration_date = None

    if day and month and year:
        try:
            # Intentar estructurar la fecha ingresada manualmente
            expiration_date = date(int(year), int(month), int(day))
            if expiration_date < date.today():
                errors['expiration_date'] = 'La fecha ingresada no puede ser menor a la fecha actual.'
        except ValueError:
            errors['expiration_date'] = 'La fecha ingresada en los casilleros no es válida.'
    else:
        # Si venían vacíos o bloqueados por ser un tipo de producto automático, se registra la fecha actual por defecto
        expiration_date = date.today()

    is_valid = len(errors) == 0

    # Diccionario mapeado listo para enviar al Service y Repository
    validated_data = {
        'name': name,
        'sku': cleaned_sku,
        'product_type_id': int(product_type_id) if product_type_id and str(product_type_id).isdigit() else None,
        'unit_of_measure': unit_of_measure if is_valid else '',
        'technical_description': technical_description,
        'expiration_date': expiration_date,  # Se inyecta la fecha limpia calculada
        'is_active': True
    }

    return is_valid, errors, validated_data