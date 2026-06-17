# app/logistics/routes/supplier_routes.py
from flask import Blueprint, render_template, request, redirect, flash, url_for
# Asegúrate de importar tu conexión a la base de datos (aquí asumo que se llama 'db' o la pasas desde tu app)
# de igual manera importamos las clases de tus capas:
from app.logistics.requests.supplier_request import SupplierRequest
from app.logistics.services.supplier_service import SupplierService
from app.logistics.repositories.supplier_repository import SupplierRepository

suppliers_bp = Blueprint('suppliers', __name__)

# Nota: Necesitas tener acceso a tu objeto de conexión de base de datos de PostgreSQL.
# Si usas una variable global o una extensión, asegúrate de importarla aquí.
# Por ejemplo: from app import get_db_connection 

@suppliers_bp.route('/suppliers/register', methods=['GET'])
def show_register_form():
    # Le indicamos a Flask la subcarpeta exacta donde está el HTML
    return render_template('logistics/register-supplier.html')

@suppliers_bp.route('/suppliers/register', methods=['POST'])
def handle_register():
    try:
        # 1. Empaquetamos los datos del formulario en el Request Object para validarlos automáticamente
        supplier_request = SupplierRequest(request.form)
        
        # 2. Inicializamos las capas pasándole la conexión a la base de datos
        # (Reemplaza 'conexion_db' por la variable real que uses en tu proyecto para conectar con Postgres)
        db_conn = conexion_db 
        repository = SupplierRepository(db_conn)
        service = SupplierService(repository)
        
        # 3. Ejecutamos la lógica de negocio y guardamos en la base de datos
        generated_id = service.register_new_supplier(supplier_request)
        
        # 4. Avisamos al usuario que todo salió perfecto
        flash(f"¡Proveedor registrado con éxito! ID asignado: {generated_id}", "success")
        
    except ValueError as e:
        # Por si falla la validación de longitudes de tu Request Object o campos vacíos
        flash(f"Error de validación: {str(e)}", "danger")
    except Exception as e:
        # Por si ocurre algún problema con la conexión de la base de datos
        flash(f"Ocurrió un error inesperado al guardar: {str(e)}", "danger")
        
    return redirect(url_for('logistics.suppliers.show_register_form'))