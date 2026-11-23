import re
from sqlalchemy.exc import DataError
from flask import render_template, request, redirect, url_for, flash, jsonify
from app.extensions import db
from app.inventory.services.products_service import ProductService
from app.inventory.requests.products_request import validate_product_form
from app.inventory.repositories.products_repository import ProductRepository
from app.models.inventory_model import (
    ProductType,
    PRODUCT_NUMERIC_MAX,
    PRODUCT_NUMERIC_MAX_LABEL,
)
from app.inventory import inventory_bp


def _form_context(**extra):
    """Contexto común del formulario, incluyendo el límite real de la BD."""
    context = {
        'numeric_max': str(PRODUCT_NUMERIC_MAX),
        'numeric_max_label': PRODUCT_NUMERIC_MAX_LABEL,
    }
    context.update(extra)
    return context


def _range_error_message():
    return ('El valor ingresado está fuera del rango permitido por la base de datos. '
            f'El máximo es {PRODUCT_NUMERIC_MAX_LABEL} para el límite de merma y '
            'para el mínimo de stock.')


# CAMBIO: Importamos el decorador dinámico
from app.decorators.roles import require_roles 

@inventory_bp.route('/products/create', methods=['GET', 'POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def create_product():
    product_types = ProductType.query.filter_by(is_active=True).order_by(ProductType.name).all()
    
    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form)

        if is_valid:
            try:
                ProductService.create_product(validated_data)
            except DataError:
                db.session.rollback()
                errors['general'] = _range_error_message()
            except ValueError as exc:
                db.session.rollback()
                errors['general'] = str(exc)
            else:
                flash('Insumo registrado exitosamente.', 'insumo-success')
                return redirect(url_for('inventory.list_products'))

        return render_template('inventory/product_form.html',
                               **_form_context(data=request.form, errors=errors,
                                               product_types=product_types))

    return render_template('inventory/product_form.html',
                           **_form_context(data={}, errors={}, product_types=product_types))


@inventory_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def edit_product(product_id):
    product = ProductService.get_product_by_id(product_id)
    product_types = ProductType.query.all()

    if not product:
        flash('El insumo que intenta editar no existe.', 'insumo-danger')
        return redirect(url_for('inventory.list_products'))

    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form, current_product_id=product_id)

        if is_valid:
            try:
                ProductService.update_product(product_id, validated_data)
            except DataError:
                db.session.rollback()
                errors['general'] = _range_error_message()
            except ValueError as exc:
                db.session.rollback()
                errors['general'] = str(exc)
            else:
                flash('Insumo actualizado correctamente.', 'insumo-success')
                return redirect(url_for('inventory.list_products'))

        return render_template('inventory/product_form.html',
                               **_form_context(product=product, data=request.form,
                                               errors=errors,
                                               product_types=product_types))

    # CAMBIO AQUÍ: Mapeamos product_type_id al diccionario de edición
    data = {
        'name': product.name,
        'product_type_id': product.product_type_id,
        'unit_of_measure': product.unit_of_measure,
        'sku': product.sku,
        'technical_description': product.technical_description,
        'waste_limit': product.waste_limit,
        'min_stock': product.min_stock,
    }

    return render_template('inventory/product_form.html',
                           **_form_context(product=product, data=data, errors={},
                                           product_types=product_types))


@inventory_bp.route('/products/check_sku', methods=['POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def check_sku():
    data = request.get_json()
    raw_sku = data.get('sku', '')
    current_product_id = data.get('product_id')
    
    cleaned_sku = re.sub(r'[^A-Z0-9-]', '', raw_sku.upper())
    
    if not cleaned_sku:
        return jsonify({'exists': False})
        
    existing_product = ProductRepository.find_by_sku(cleaned_sku)
    
    if existing_product:
        if current_product_id and str(existing_product.id) == str(current_product_id):
            return jsonify({'exists': False})
        return jsonify({'exists': True})
        
    return jsonify({'exists': False})
