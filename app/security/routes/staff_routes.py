from flask import Blueprint, render_template, request, jsonify
from app.security.services.staff_service import StaffService
from app.security.requests.staff_validators import validate_staff_update

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')

@staff_bp.route('/listado', methods=['GET'])
def list_staff():
    data = StaffService.get_staff_list_data()
    return render_template(
        'security/staff_list.html', 
        users=data['staff'], 
        roles=data['roles'], 
        locations=data['locations']
    )

@staff_bp.route('/editar/<int:user_id>', methods=['POST'])
def edit_staff(user_id):
    data = request.get_json()
    
    # Extraemos el flag 'activo' enviado desde JS si el usuario se quedó sin sedes.
    # Usamos .pop() para removerlo del diccionario y evitar que rompa 'validate_staff_update'
    desactivar_por_sedes = data.pop('activo', None) is False
    
    # 1. Validar datos básicos (Email, Rol, Locations)
    errors = validate_staff_update(data)
    if errors:
        return jsonify({'success': False, 'message': errors[0]}), 400
    
    # 2. Llamar al servicio para actualizar los datos base
    success, message = StaffService.actualizar_usuario(user_id, data)
    
    # 3. REGLA DE NEGOCIO: Si se editó con éxito pero se quedó sin sedes, forzamos su desactivación
    if success and desactivar_por_sedes:
        StaffService.actualizar_estado(user_id, False)
    
    return jsonify({'success': success, 'message': message})

@staff_bp.route('/toggle-status/<int:user_id>', methods=['POST'])
def toggle_status(user_id):
    data = request.get_json()
    nuevo_estado = data.get('activo')
    exito, mensaje = StaffService.actualizar_estado(user_id, nuevo_estado)
    return jsonify({"success": exito, "message": mensaje})