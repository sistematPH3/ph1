from flask import Blueprint, render_template, request, redirect, flash, url_for
from app.extensions import db
from app.logistics.requests.supplier_request import SupplierRequest
from app.logistics.services.supplier_service import SupplierService
from app.logistics.repositories.supplier_repository import SupplierRepository

suppliers_bp = Blueprint('suppliers', __name__)

@suppliers_bp.route('/suppliers/register', methods=['GET'])
def show_register_form():
    return render_template('logistics/register-supplier.html')

@suppliers_bp.route('/suppliers/register', methods=['POST'])
def handle_register():
    try:
        supplier_request = SupplierRequest(request.form)
        
        db_conn = db
        repository = SupplierRepository(db_conn)
        service = SupplierService(repository)
        
        generated_id = service.register_new_supplier(supplier_request)
        
        flash(f"¡Proveedor registrado con éxito! ID asignado: {generated_id}", "success")
        
    except ValueError as e:
        flash(f"Error de validación: {str(e)}", "danger")
    except Exception as e:
        flash(f"Ocurrió un error inesperado al guardar: {str(e)}", "danger")
        
    return redirect(url_for('suppliers.show_register_form'))