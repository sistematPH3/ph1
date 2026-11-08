from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Supplier  # Modelo de la tabla de proveedores
from app.logistics.requests.supplier_request import SupplierRequest
from app.logistics.services.supplier_service import SupplierService
from app.logistics.repositories.supplier_repository import SupplierRepository

# Importamos el decorador dinámico unificado
from app.decorators.roles import require_roles

suppliers_bp = Blueprint('suppliers', __name__)

@suppliers_bp.route('/suppliers/register', methods=['GET'])
@require_roles('admin', 'management', 'manager')
def show_register_form():
    return render_template('logistics/register-supplier.html')

@suppliers_bp.route('/suppliers/register', methods=['POST'])
@require_roles('admin', 'management', 'manager')
def handle_register():
    try:
        supplier_request = SupplierRequest(request.form)
        repository = SupplierRepository(db)
        service = SupplierService(repository)
        
        generated_id = service.register_new_supplier(supplier_request)
        
        flash(f"¡Proveedor registrado con éxito! ID asignado: {generated_id}", "success")
        
    except ValueError as e:
        flash(str(e), "danger")
    except IntegrityError:
        db.session.rollback()
        flash("No se pudo registrar: El RIF, Nombre o Correo ingresado ya pertenece a otro proveedor.", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Ocurrió un error inesperado al guardar: {str(e)}", "danger")
        
    return redirect(url_for('logistics.suppliers.show_register_form'))

# =========================================================================
# RUTAS DE VALIDACIÓN EN TIEMPO REAL (AJAX)
# =========================================================================

@suppliers_bp.route('/suppliers/check-name', methods=['POST'])
@login_required
def check_name():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    
    try:
        sup_id = int(data.get('supplier_id')) if data.get('supplier_id') else 0
    except (ValueError, TypeError):
        sup_id = 0
    
    exists = Supplier.query.filter(
        Supplier.name.ilike(name), 
        Supplier.id != sup_id
    ).first()
    
    return jsonify({"available": exists is None})


@suppliers_bp.route('/suppliers/check-tax-id', methods=['POST'])
@login_required
def check_tax_id():
    data = request.get_json() or {}
    tax_id = data.get('tax_id', '').strip()
    
    try:
        sup_id = int(data.get('supplier_id')) if data.get('supplier_id') else 0
    except (ValueError, TypeError): 
        sup_id = 0

    exists = Supplier.query.filter(
        Supplier.tax_id.ilike(tax_id), 
        Supplier.id != sup_id
    ).first()
    
    return jsonify({"available": exists is None})


@suppliers_bp.route('/suppliers/check-phone', methods=['POST'])
@login_required
def check_phone():
    data = request.get_json() or {}
    phone = data.get('phone', '').strip()
    
    try:
        sup_id = int(data.get('supplier_id')) if data.get('supplier_id') else 0
    except (ValueError, TypeError): 
        sup_id = 0

    exists = Supplier.query.filter(
        Supplier.phone == phone, 
        Supplier.id != sup_id
    ).first()
    
    return jsonify({"available": exists is None})


@suppliers_bp.route('/suppliers/check-email', methods=['POST'])
@login_required
def check_email():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    
    try:
        sup_id = int(data.get('supplier_id')) if data.get('supplier_id') else 0
    except (ValueError, TypeError): 
        sup_id = 0

    exists = Supplier.query.filter(
        Supplier.email.ilike(email), 
        Supplier.id != sup_id
    ).first()
    
    return jsonify({"available": exists is None})