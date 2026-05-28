from flask import render_template, request, redirect, url_for, flash
from app.inventory import inventory_bp
from app.inventory.requests.products_request import validate_product_form
from app.models.inventory_model import Category, Product
from app.inventory.services.products_service import ProductService

@inventory_bp.route('/products/new', methods=['GET', 'POST'])
def create_product():
    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form)

        if not is_valid:
            categories = Category.query.all()
            return render_template('product_form.html', categories=categories, errors=errors, data=request.form)

        try:
            ProductService.create_product(validated_data)
            flash('Producto registrado exitosamente.', 'success')
            return redirect(url_for('inventory.list_products'))
        except Exception as e:
            categories = Category.query.all()
            return render_template('product_form.html', categories=categories, errors={'general': str(e)}, data=request.form)

    categories = Category.query.all()
    return render_template('product_form.html', categories=categories, errors={}, data={})

@inventory_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        is_valid, errors, validated_data = validate_product_form(request.form)

        if not is_valid:
            categories = Category.query.all()
            return render_template('product_form.html', categories=categories, product=product, errors=errors, data=request.form)

        try:
            ProductService.update_product(product_id, validated_data)
            flash('Producto actualizado exitosamente.', 'success')
            return redirect(url_for('inventory.list_products'))
        except Exception as e:
            categories = Category.query.all()
            return render_template('product_form.html', categories=categories, product=product, errors={'general': str(e)}, data=request.form)

    categories = Category.query.all()
    
    data = {
        'name': product.name,
        'sku': product.sku,
        'category_id': product.category_id,
        'quantity': product.quantity,
        'unit_of_measure': product.unit_of_measure,
        'technical_description': product.technical_description
    }
    
    return render_template('product_form.html', categories=categories, product=product, errors={}, data=data)