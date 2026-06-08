import re
from flask import render_template, request, redirect, url_for, flash, jsonify
from app.inventory.services.products_service import ProductService
from app.inventory.requests.products_request import validate_product_form
from app.inventory.repositories.products_repository import ProductRepository
from app.inventory import inventory_bp

@inventory_bp.route('/products/create', methods=['GET', 'POST'])
def create_product():
    categories = [
        type('Category', (), {'id': 1, 'name': 'Secos'}),
        type('Category', (), {'id': 2, 'name': 'Lacteos'}),
        type('Category', (), {'id': 3, 'name': 'Embutidos'}),
        type('Category', (), {'id': 4, 'name': 'Vegetales Frescos'}),
        type('Category', (), {'id': 5, 'name': 'Salsas y Liquido'}),
        type('Category', (), {'id': 6, 'name': 'Utensilios y Empaques'})
    ]
    
    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form)

        if is_valid:
            ProductService.create_product(validated_data)
            flash('Insumo registrado exitosamente.', 'success')
            return redirect(url_for('inventory.list_products'))
            
        return render_template('inventory/product_form.html', 
                               data=request.form, 
                               errors=errors, 
                               categories=categories)

    return render_template('inventory/product_form.html', data={}, errors={}, categories=categories)


@inventory_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = ProductService.get_product_by_id(product_id)
    
    categories = [
        type('Category', (), {'id': 1, 'name': 'Secos'}),
        type('Category', (), {'id': 2, 'name': 'Lacteos'}),
        type('Category', (), {'id': 3, 'name': 'Embutidos'}),
        type('Category', (), {'id': 4, 'name': 'Vegetales Frescos'}),
        type('Category', (), {'id': 5, 'name': 'Salsas y Liquido'}),
        type('Category', (), {'id': 6, 'name': 'Utensilios y Empaques'})
    ]

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
                               product=product, 
                               data=request.form, 
                               errors=errors, 
                               categories=categories)

    data = {
        'name': product.name,
        'category_id': product.category_id,
        'unit_of_measure': product.unit_of_measure,
        'quantity': product.quantity,
        'sku': product.sku,
        'technical_description': product.technical_description
    }

    return render_template('inventory/product_form.html', product=product, data=data, errors={}, categories=categories)


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