from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Supplier

from app.logistics.repositories.supplier_list_repository import SupplierListRepository
from app.logistics.services.supplier_list_service import SupplierListService
from app.logistics.requests.supplier_list_request import SupplierListFilterRequest

supplier_list_bp = Blueprint('supplier_list', __name__)
filter_request_validator = SupplierListFilterRequest()

def check_supplier_roles():
    """Verifica si el usuario actual tiene permisos para ver proveedores."""
    roles_permitidos = ['Administrator', 'Management', 'Manager']
    user_role_name = current_user.role.name if hasattr(current_user.role, 'name') else current_user.role
    
    # Si no tiene el rol, lanza el error 403 (Pantalla de Prohibido)
    if user_role_name not in roles_permitidos:
        abort(403)

def get_supplier_list_service():
    repository = SupplierListRepository(db)
    return SupplierListService(repository)


# 1. VISTA PRINCIPAL DEL LISTADO
@supplier_list_bp.route('/suppliers/list', methods=['GET'], strict_slashes=False)
@login_required
def index():
    check_supplier_roles() # Muestra "Prohibido" si no tiene el rol
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
    except Exception as e:
        flash(f"Error interno en el sistema: {str(e)}", "danger")
        return render_template('logistics/suppliers_list.html', suppliers=[], current_status='')


# 2. VISTA PARA MOSTRAR EL FORMULARIO DE REGISTRO
@supplier_list_bp.route('/suppliers/register', methods=['GET'])
@login_required
def register_supplier_view():
    check_supplier_roles()
    try:
        return render_template('logistics/register-supplier.html', supplier=None)
    except Exception as e:
        flash(f"Error al abrir el formulario de registro: {str(e)}", "danger")
        return redirect(url_for('supplier_list.index'))


# 3. PROCESAR EL REGISTRO DE UN NUEVO PROVEEDOR (POST)
@supplier_list_bp.route('/suppliers/register', methods=['POST'])
@login_required
def handle_register_supplier():
    check_supplier_roles()
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
        return redirect(url_for('supplier_list.index'))
    except Exception as e:
        db.session.rollback()
        flash(f"Error al registrar el proveedor: {str(e)}", "danger")
        return render_template('logistics/register-supplier.html', supplier=None)


# 4. VISTA PARA MOSTRAR EL FORMULARIO DE EDICIÓN
@supplier_list_bp.route('/suppliers/edit/<int:supplier_id>', methods=['GET'])
@login_required
def edit_supplier_view(supplier_id):
    check_supplier_roles()
    try:
        service = get_supplier_list_service()
        supplier = service.repository.get_by_id(supplier_id)
        
        if not supplier:
            flash("El proveedor que intenta editar no existe.", "warning")
            return redirect(url_for('supplier_list.index'))
            
        return render_template('logistics/register-supplier.html', supplier=supplier)
    except Exception as e:
        flash(f"Error al cargar los datos del proveedor para edición: {str(e)}", "danger")
        return redirect(url_for('supplier_list.index'))


# 5. PROCESAR LA ACTUALIZACIÓN DE UN PROVEEDOR EXISTENTE (POST)
@supplier_list_bp.route('/suppliers/edit/<int:supplier_id>', methods=['POST'])
@login_required
def handle_edit_supplier(supplier_id):
    check_supplier_roles()
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
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar el proveedor: {str(e)}", "danger")
        return redirect(url_for('supplier_list.index'))


# 6. FUNCIONALIDAD DEL TOGGLE DE ESTADO
@supplier_list_bp.route('/suppliers/list/<int:supplier_id>/toggle', methods=['POST'])
@login_required
def toggle_status(supplier_id):
    check_supplier_roles()
    try:
        service = get_supplier_list_service()
        new_status = service.process_status_toggle(supplier_id)
        
        if not new_status:
            return jsonify({"success": False, "error": "Proveedor no encontrado"}), 404
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": True, "new_status": new_status}), 200
            
        flash("Estado del proveedor actualizado con éxito.", "success")
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"Error al cambiar el estado: {str(e)}", "danger")
        
    return redirect(url_for('supplier_list.index'))