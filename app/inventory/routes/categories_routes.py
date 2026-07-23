import re
import unicodedata
from flask import render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy.exc import IntegrityError
from app import db
from app.inventory import inventory_bp
from app.inventory.services.category_service import CategoryService

# CAMBIO: Importamos el decorador dinámico
from app.decorators.roles import require_roles 


def normalize_text(text: str) -> str:
    """
    Normaliza una cadena eliminando espacios, tildes/diacríticos, convirtiéndola a minúsculas,
    colapsando letras repetidas consecutivas y removiendo terminaciones plurales ('es' o 's').
    """
    if not text:
        return ""
    normalized = unicodedata.normalize('NFD', text.strip().lower())
    no_accents = "".join(c for c in normalized if unicodedata.category(c) != 'Mn')
    collapsed = re.sub(r'(.)\1+', r'\1', no_accents)
    return re.sub(r'(es|s+)$', '', collapsed)


@inventory_bp.route('/categories', methods=['GET'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def list_categories():
    product_types = CategoryService.get_all_product_types()
    return render_template('inventory/categories_list.html', product_types=product_types)


@inventory_bp.route('/categories/create', methods=['GET', 'POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def create_category():
    all_types = CategoryService.get_all_product_types()
    existing_names = [pt.name for pt in all_types]

    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        if not name:
            return render_template(
                'inventory/category_form.html',
                data=request.form,
                existing_categories=existing_names,
                errors={'name': 'El nombre de la categoría es obligatorio.'}
            )

        norm_name = normalize_text(name)
        match = next((pt for pt in all_types if normalize_text(pt.name) == norm_name), None)

        if match:
            return render_template(
                'inventory/category_form.html',
                data=request.form,
                existing_categories=existing_names,
                errors={'name': f'La categoría "{match.name}" ya se encuentra registrada.'}
            )

        try:
            CategoryService.create_category(request.form)
            flash('Categoría registrada exitosamente.', 'success')
            return redirect(url_for('inventory.list_categories'))

        except IntegrityError:
            db.session.rollback()
            return render_template(
                'inventory/category_form.html',
                data=request.form,
                existing_categories=existing_names,
                errors={'name': f'La categoría ya se encuentra registrada.'}
            )

        except Exception as e:
            db.session.rollback()
            return render_template(
                'inventory/category_form.html',
                data=request.form,
                existing_categories=existing_names,
                errors={'general': f'Error al registrar: {str(e)}'}
            )

    return render_template('inventory/category_form.html', data={}, existing_categories=existing_names, errors={})


@inventory_bp.route('/categories/edit/<int:type_id>', methods=['GET', 'POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def edit_category(type_id):
    product_type = CategoryService.get_product_type_by_id(type_id)
    if not product_type:
        flash('Categoría no encontrada.', 'danger')
        return redirect(url_for('inventory.list_categories'))

    all_types = CategoryService.get_all_product_types()
    existing_names = [pt.name for pt in all_types if pt.id != type_id]

    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        if not name:
            return render_template(
                'inventory/category_form.html',
                product_type=product_type,
                data=request.form,
                existing_categories=existing_names,
                errors={'name': 'El nombre de la categoría es obligatorio.'}
            )

        norm_name = normalize_text(name)
        match = next((pt for pt in all_types if pt.id != type_id and normalize_text(pt.name) == norm_name), None)

        if match:
            return render_template(
                'inventory/category_form.html',
                product_type=product_type,
                data=request.form,
                existing_categories=existing_names,
                errors={'name': f'La categoría "{match.name}" ya se encuentra registrada.'}
            )

        try:
            CategoryService.update_category(type_id, request.form)
            flash('Categoría actualizada exitosamente.', 'success')
            return redirect(url_for('inventory.list_categories'))

        except IntegrityError:
            db.session.rollback()
            return render_template(
                'inventory/category_form.html',
                product_type=product_type,
                data=request.form,
                existing_categories=existing_names,
                errors={'name': f'La categoría ya se encuentra registrada.'}
            )

        except Exception as e:
            db.session.rollback()
            return render_template(
                'inventory/category_form.html',
                product_type=product_type,
                data=request.form,
                existing_categories=existing_names,
                errors={'general': f'Error al actualizar: {str(e)}'}
            )

    data = {
        'name': product_type.name,
        'shelf_life_days': product_type.shelf_life_days or 0,
        'requires_manual_date': product_type.requires_manual_date
    }

    return render_template('inventory/category_form.html', product_type=product_type, data=data, existing_categories=existing_names, errors={})


@inventory_bp.route('/categories/<int:type_id>/toggle-status', methods=['POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def toggle_category_status(type_id):
    try:
        product_type = CategoryService.get_product_type_by_id(type_id)
        if not product_type:
            return jsonify({"success": False, "error": "Categoría no encontrada"}), 404

        product_type.is_active = not getattr(product_type, 'is_active', True)
        db.session.commit()

        return jsonify({"success": True, "is_active": product_type.is_active}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@inventory_bp.route('/categories/api/create', methods=['POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def api_create_category():
    try:
        raw_data = request.get_json() if request.is_json else request.form.to_dict()
        cat_name = str(raw_data.get('name', '')).strip()

        if not cat_name:
            return jsonify({'success': False, 'error': 'El nombre de la categoría es obligatorio.'}), 400

        existing = CategoryService.get_all_product_types()
        norm_cat_name = normalize_text(cat_name)

        match = next((c for c in existing if normalize_text(c.name) == norm_cat_name), None)

        if match:
            return jsonify({
                'success': False,
                'error': f'La categoría "{match.name}" ya se encuentra registrada.'
            }), 400

        formatted_data = {
            'name': cat_name,
            'requires_manual_date': 'true' if str(raw_data.get('requires_manual_date')).lower() in ['true', '1', 'on'] else '',
            'shelf_life_days': str(raw_data.get('shelf_life_days', 0))
        }

        new_category = CategoryService.create_category(formatted_data)

        return jsonify({
            'success': True,
            'category': {
                'id': new_category.id,
                'name': new_category.name,
                'requires_manual_date': bool(new_category.requires_manual_date),
                'shelf_life_days': new_category.shelf_life_days or 0
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error al crear categoría: {str(e)}'}), 500