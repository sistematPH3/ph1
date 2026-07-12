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
    
    # 1. Validar datos
    errors = validate_staff_update(data)
    if errors:
        return jsonify({'success': False, 'message': errors[0]}), 400
    
    # 2. Llamar al servicio para actualizar
    success, message = StaffService.actualizar_usuario(user_id, data)
    return jsonify({'success': success, 'message': message})

@staff_bp.route('/toggle-status/<int:user_id>', methods=['POST'])
def toggle_status(user_id):
    data = request.get_json()
    nuevo_estado = data.get('activo')
    exito, mensaje = StaffService.actualizar_estado(user_id, nuevo_estado)
    return jsonify({"success": exito, "message": mensaje})