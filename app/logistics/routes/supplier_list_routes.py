# app/logistics/routes/supplier_list_routes.py
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.extensions import db
from app.models import Supplier  # Importamos el modelo

from app.logistics.repositories.supplier_list_repository import SupplierListRepository
from app.logistics.services.supplier_list_service import SupplierListService
from app.logistics.requests.supplier_list_request import SupplierListFilterRequest

supplier_list_bp = Blueprint('supplier_list', __name__)
filter_request_validator = SupplierListFilterRequest()

def supplier_access_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Validamos que el usuario cumpla con al menos uno de los tres roles permitidos
        if not (current_user.is_admin or current_user.is_management or current_user.is_manager):
            flash("Acceso denegado: Se requieren privilegios de Administrador, Director o Gerente.", "danger")
            return redirect(url_for('security.login')) # Redirige al login igual que los otros decoradores
        return f(*args, **kwargs)
    return decorated_function

def get_supplier_list_service():
    """Instancia de forma limpia el servicio inyectándole el repositorio"""
    repository = SupplierListRepository(db)
    return SupplierListService(repository)

# 1. VISTA PRINCIPAL DEL LISTADO
@supplier_list_bp.route('/suppliers/list', methods=['GET'], strict_slashes=False)
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
    except Exception as e:
        flash(f"Error interno en el sistema: {str(e)}", "danger")
        return render_template('logistics/suppliers_list.html', suppliers=[], current_status='')


# 2. VISTA PARA MOSTRAR EL FORMULARIO DE REGISTRO
@supplier_list_bp.route('/suppliers/register', methods=['GET'])
def register_supplier_view():
    try:
        return render_template('logistics/register-supplier.html', supplier=None)
    except Exception as e:
        flash(f"Error al abrir el formulario de registro: {str(e)}", "danger")
        return redirect(url_for('supplier_list.index'))


# 3. PROCESAR EL REGISTRO DE UN NUEVO PROVEEDOR (POST) - CORREGIDO
@supplier_list_bp.route('/suppliers/register', methods=['POST'])
def handle_register_supplier():
    try:
        # Capturamos los datos enviados desde el formulario
        name = request.form.get('name')
        tax_id = request.form.get('tax_id')
        contact_name = request.form.get('contact_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        status = request.form.get('status', 'Active')

        # CORRECCIÓN: Instanciamos vacío y asignamos los atributos uno a uno
        new_supplier = Supplier()
        new_supplier.name = name
        new_supplier.tax_id = tax_id
        new_supplier.contact_name = contact_name
        new_supplier.email = email
        new_supplier.phone = phone
        new_supplier.status = status.upper() # ACTIVE / INACTIVE
        
        # Guardamos en la base de datos de manera limpia
        db.session.add(new_supplier)
        db.session.commit()
        
        flash("Proveedor registrado exitosamente.", "success")
        return redirect(url_for('supplier_list.index'))
    except Exception as e:
        db.session.rollback() # Ante cualquier error, revertimos la transacción
        flash(f"Error al registrar el proveedor: {str(e)}", "danger")
        return render_template('logistics/register-supplier.html', supplier=None)


# 4. VISTA PARA MOSTRAR EL FORMULARIO DE EDICIÓN
@supplier_list_bp.route('/suppliers/edit/<int:supplier_id>', methods=['GET'])
def edit_supplier_view(supplier_id):
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
def handle_edit_supplier(supplier_id):
    try:
        service = get_supplier_list_service()
        supplier = service.repository.get_by_id(supplier_id)
        
        if not supplier:
            flash("El proveedor no existe o fue eliminado.", "warning")
            return redirect(url_for('supplier_list.index'))
            
        # Actualizamos los campos de la instancia existente con los datos del POST
        supplier.name = request.form.get('name')
        supplier.tax_id = request.form.get('tax_id')
        supplier.contact_name = request.form.get('contact_name')
        supplier.email = request.form.get('email')
        supplier.phone = request.form.get('phone')
        supplier.status = request.form.get('status', 'Active').upper()
        
        # Guardamos los cambios
        db.session.commit()
        
        flash("Proveedor actualizado exitosamente.", "success")
        return redirect(url_for('supplier_list.index'))
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar el proveedor: {str(e)}", "danger")
        return redirect(url_for('supplier_list.index'))


# 6. FUNCIONALIDAD DEL TOGGLE DE ESTADO (CAMBIO DE STATUS ACTIVADO/DESACTIVADO)
@supplier_list_bp.route('/suppliers/list/<int:supplier_id>/toggle', methods=['POST'])
def toggle_status(supplier_id):
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