import re
from flask import render_template, request, redirect, url_for, flash, jsonify
from app.inventory.services.products_service import ProductService
from app.inventory.requests.products_request import validate_product_form
from app.inventory.repositories.products_repository import ProductRepository
# CAMBIO: Importamos ProductType desde tus modelos reales
from app.models.inventory_model import ProductType 
from app.inventory import inventory_bp

@inventory_bp.route('/products/create', methods=['GET', 'POST'])
def create_product():
    # CAMBIO AQUÍ: Traemos los tipos de productos directo de la Base de Datos
    product_types = ProductType.query.all()
    
    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form)

        if is_valid:
            ProductService.create_product(validated_data)
            flash('Insumo registrado exitosamente.', 'success')
            return redirect(url_for('inventory.list_products'))
            
        return render_template('inventory/product_form.html', 
                               data=request.form, \
                               errors=errors, \
                               product_types=product_types) # Pasamos product_types

    return render_template('inventory/product_form.html', data={}, errors={}, product_types=product_types)


@inventory_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = ProductService.get_product_by_id(product_id)
    # CAMBIO AQUÍ: Traemos los tipos de productos reales
    product_types = ProductType.query.all()

    if not product:
        flash('El insumo que intenta editar no existe.', 'danger')
        return redirect(url_for('inventory.list_products'))

    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form, current_product_id=product_id)

        if is_valid:
            ProductService.update_product(product_id, validated_data)
            flash('Insumo actualizado correctamente.', 'success')
            return redirect(url_for('inventory.list_products'))

        return render_template('inventory/product_form.html', 
                               product=product, \
                               data=request.form, \
                               errors=errors, \
                               product_types=product_types)

    # CAMBIO AQUÍ: Mapeamos product_type_id al diccionario de edición
    data = {
        'name': product.name,
        'product_type_id': product.product_type_id,
        'unit_of_measure': product.unit_of_measure,
        'quantity': product.quantity,
        'sku': product.sku,
        'technical_description': product.technical_description
    }

    return render_template('inventory/product_form.html', product=product, data=data, errors={}, product_types=product_types)


@inventory_bp.route('/products/check_sku', methods=['POST'])
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