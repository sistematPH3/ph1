from flask import render_template, request, redirect, url_for, flash
from app import db
from app.inventory import inventory_bp
from app.inventory.services.category_service import CategoryService

@inventory_bp.route('/categories', methods=['GET'])
def list_categories():
    product_types = CategoryService.get_all_product_types()
    return render_template('inventory/categories_list.html', product_types=product_types)


@inventory_bp.route('/categories/create', methods=['GET', 'POST'])
def create_category():
    if request.method == 'POST':
        try:
            CategoryService.create_category(request.form)
            flash('Categoría registrada exitosamente.', 'success')
            return redirect(url_for('inventory.list_categories'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: {str(e)}', 'danger')

    return render_template('inventory/category_form.html', data={}, errors={})


@inventory_bp.route('/categories/edit/<int:type_id>', methods=['GET', 'POST'])
def edit_category(type_id):
    product_type = CategoryService.get_product_type_by_id(type_id)
    
    if request.method == 'POST':
        try:
            CategoryService.update_category(type_id, request.form)
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

@inventory_bp.route('/categories/<int:type_id>/toggle-status', methods=['POST'])
def toggle_category_status(type_id):
    try:
        product_type = CategoryService.get_product_type_by_id(type_id)
        if not product_type:
            return {"success": False, "error": "Categoría no encontrada"}, 404
            
        # Invierte el estado actual
        product_type.is_active = not getattr(product_type, 'is_active', True)
        db.session.commit()
        
        return {"success": True, "is_active": product_type.is_active}, 200
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}, 500