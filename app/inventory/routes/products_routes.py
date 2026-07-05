import re
from flask import render_template, request, redirect, url_for, flash, jsonify
from app.inventory.services.products_service import ProductService
from app.inventory.requests.products_request import validate_product_form
from app.inventory.repositories.products_repository import ProductRepository
# CAMBIO: Importamos ProductType desde tus modelos reales
from app.models.inventory_model import ProductType, Category 
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

@inventory_bp.route('/categories', methods=['GET'])
def list_categories():
    # Recuperamos los tipos de productos que contienen las reglas operativas
    product_types = ProductType.query.order_by(ProductType.name).all()
    return render_template('inventory/categories_list.html', product_types=product_types)


@inventory_bp.route('/categories/create', methods=['GET', 'POST'])
def create_category():
    from app import db  # Importación segura interna
    
    if request.method == 'POST':
        name = request.form.get('name')
        shelf_life_days = request.form.get('shelf_life_days', 0)
        requires_manual_date = bool(request.form.get('requires_manual_date'))

        try:
            shelf_life_days = int(shelf_life_days) if shelf_life_days else None
        except ValueError:
            shelf_life_days = None

        try:
            # 🚀 SOLUCIÓN: Buscamos si ya existe una Categoría Macro con el NOMBRE REAL
            category = Category.query.filter_by(name=name).first()
            
            # Si no existe, creamos un registro nuevo en la tabla 'categories' con el nombre real
            if not category:
                category = Category(name=name)
                db.session.add(category)
                db.session.commit()  # Hacemos commit para generar su ID único

            # Guardamos en ProductType usando el ID de su respectiva categoría real
            new_type = ProductType(
                name=name,
                category_id=category.id,  # Vinculación uno a uno automática
                requires_manual_date=requires_manual_date,
                shelf_life_days=shelf_life_days if not requires_manual_date else None
            )
            
            db.session.add(new_type)
            db.session.commit()

            flash('Categoría registrada exitosamente.', 'success')
            return redirect(url_for('inventory.list_categories'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: {str(e)}', 'danger')

    return render_template('inventory/category_form.html', data={}, errors={})


@inventory_bp.route('/categories/edit/<int:type_id>', methods=['GET', 'POST'])
def edit_category(type_id):
    from app import db
    product_type = ProductType.query.get_or_404(type_id)
    
    if request.method == 'POST':
        new_name = request.form.get('name')
        product_type.requires_manual_date = bool(request.form.get('requires_manual_date'))
        
        shelf_life_days = request.form.get('shelf_life_days', 0)
        try:
            product_type.shelf_life_days = int(shelf_life_days) if shelf_life_days else None
        except ValueError:
            product_type.shelf_life_days = None

        try:
            # 🚀 AL EDITAR: También actualizamos el nombre real en la tabla Category vinculada
            if product_type.category_id:
                category = Category.query.get(product_type.category_id)
                if category:
                    category.name = new_name
            
            # Actualizamos el nombre en ProductType
            product_type.name = new_name
            
            db.session.commit()
            flash('Categoría actualizada exitosamente.', 'success')
            return redirect(url_for('inventory.list_categories'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')

    data = {
        'name': product_type.name,
        'shelf_life_days': product_type.shelf_life_days or 0,
        'requires_manual_date': product_type.requires_manual_date
    }
    
    return render_template('inventory/category_form.html', product_type=product_type, data=data, errors={})