import logging

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.extensions import db
from app.models import Supplier
from app.logistics.repositories.supplier_list_repository import SupplierListRepository
from app.logistics.services.supplier_list_service import SupplierListService
from app.logistics.requests.supplier_list_request import SupplierListFilterRequest
from app.decorators.roles import require_roles

logger = logging.getLogger(__name__)

supplier_list_bp = Blueprint('supplier_list', __name__)
filter_request_validator = SupplierListFilterRequest()

def get_supplier_list_service():
    repository = SupplierListRepository(db)
    return SupplierListService(repository)

@supplier_list_bp.route('/suppliers/list', methods=['GET'], strict_slashes=False)
@require_roles('admin')
def index():
    try:
        service = get_supplier_list_service()
        raw_params = {
            'search': request.args.get('search'),
            'status': request.args.get('status')
        }
        validated_data = filter_request_validator.load(raw_params)
        suppliers = service.get_formatted_suppliers(
            search_term=validated_data['search'],
            status_filter=validated_data['status']
        )
        return render_template(
            'logistics/suppliers_list.html', 
            suppliers=suppliers, 
            current_status=validated_data['status'] or ''
        )
    except ValueError as val_err:
        flash(f"Parámetros de búsqueda inválidos: {str(val_err)}", "warning")
        return render_template('logistics/suppliers_list.html', suppliers=[], current_status='')
    except Exception:
        logger.exception("Error al cargar el listado de proveedores")
        flash("No se pudo cargar el listado de proveedores. Intenta de nuevo.", "danger")
        return render_template('logistics/suppliers_list.html', suppliers=[], current_status='')

@supplier_list_bp.route('/suppliers/register', methods=['GET'])
@require_roles('admin')
def register_supplier_view():
    try:
        return render_template('logistics/register-supplier.html', supplier=None)
    except Exception:
        logger.exception("Error al abrir el formulario de registro de proveedor")
        flash("No se pudo abrir el formulario de registro. Intenta de nuevo.", "danger")
        return redirect(url_for('supplier_list.index'))

@supplier_list_bp.route('/suppliers/register', methods=['POST'])
@require_roles('admin')
def handle_register_supplier():
    try:
        name = request.form.get('name')
        tax_id = request.form.get('tax_id')
        contact_name = request.form.get('contact_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        status = request.form.get('status', 'Active')

        new_supplier = Supplier()
        new_supplier.name = name
        new_supplier.tax_id = tax_id
        new_supplier.contact_name = contact_name
        new_supplier.email = email
        new_supplier.phone = phone
        new_supplier.status = status.upper()
        
        db.session.add(new_supplier)
        db.session.commit()
        
        flash("Proveedor registrado exitosamente.", "success")
        return redirect(url_for('purchase_routes.new_purchase_form'))
    except Exception:
        db.session.rollback()
        logger.exception("Error al registrar el proveedor")
        flash("No se pudo registrar el proveedor. Intenta de nuevo.", "danger")
        return render_template('logistics/register-supplier.html', supplier=None)

@supplier_list_bp.route('/suppliers/edit/<int:supplier_id>', methods=['GET'])
@require_roles('admin')
def edit_supplier_view(supplier_id):
    try:
        service = get_supplier_list_service()
        supplier = service.repository.get_by_id(supplier_id)
        
        if not supplier:
            flash("El proveedor que intenta editar no existe.", "warning")
            return redirect(url_for('supplier_list.index'))
            
        return render_template('logistics/register-supplier.html', supplier=supplier)
    except Exception:
        logger.exception("Error al cargar el proveedor %s para edición", supplier_id)
        flash("No se pudo cargar el proveedor para edición. Intenta de nuevo.", "danger")
        return redirect(url_for('supplier_list.index'))

@supplier_list_bp.route('/suppliers/edit/<int:supplier_id>', methods=['POST'])
@require_roles('admin')
def handle_edit_supplier(supplier_id):
    try:
        service = get_supplier_list_service()
        supplier = service.repository.get_by_id(supplier_id)
        
        if not supplier:
            flash("El proveedor no existe o fue eliminado.", "warning")
            return redirect(url_for('supplier_list.index'))
            
        supplier.name = request.form.get('name')
        supplier.tax_id = request.form.get('tax_id')
        supplier.contact_name = request.form.get('contact_name')
        supplier.email = request.form.get('email')
        supplier.phone = request.form.get('phone')
        supplier.status = request.form.get('status', 'Active').upper()
        
        db.session.commit()
        
        flash("Proveedor actualizado exitosamente.", "success")
        return redirect(url_for('supplier_list.index'))
    except Exception:
        db.session.rollback()
        logger.exception("Error al actualizar el proveedor %s", supplier_id)
        flash("No se pudo actualizar el proveedor. Intenta de nuevo.", "danger")
        return redirect(url_for('supplier_list.index'))

@supplier_list_bp.route('/suppliers/list/<int:supplier_id>/toggle', methods=['POST'])
@require_roles('admin')
def toggle_status(supplier_id):
    try:
        service = get_supplier_list_service()
        new_status = service.process_status_toggle(supplier_id)
        
        if not new_status:
            return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": True, "new_status": new_status}), 200
            
        flash("Estado del proveedor actualizado con éxito.", "success")
    except Exception:
        logger.exception("Error al cambiar el estado del proveedor %s", supplier_id)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                "success": False,
                "error": "No se pudo cambiar el estado del proveedor. Intenta de nuevo.",
            }), 500
        flash("No se pudo cambiar el estado del proveedor. Intenta de nuevo.", "danger")
        
    return redirect(url_for('supplier_list.index'))