from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import text
from app.extensions import db
from app.logistics.services.user_list_service import UserListService
from app.logistics.requests.user_list_validators import validate_sede_assignment

logistics_users_bp = Blueprint('logistics_users', __name__)

@logistics_users_bp.route('/users/view', methods=['GET'])
def users_page():
    return render_template('logistics/user_list.html')

@logistics_users_bp.route('/users', methods=['GET'])
def list_users():
    try:
        users = UserListService.get_users_list()
        return jsonify({
            "status": "success",
            "data": users
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@logistics_users_bp.route('/users/sedes', methods=['GET'])
def list_sedes():
    try:
        query = text("SELECT id, name FROM locations WHERE is_active = true")
        result = db.session.execute(query).fetchall()
        
        sedes = [{"id": row.id, "name": row.name} for row in result]
            
        return jsonify({
            "status": "success",
            "data": sedes
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@logistics_users_bp.route('/users/assign-sede', methods=['PUT'])
def assign_sede():
    try:
        data = request.get_json()
        errors = validate_sede_assignment(data)
        
        if errors:
            return jsonify({
                "status": "error", 
                "message": "Datos inválidos", 
                "errors": errors
            }), 400
            
        success = UserListService.assign_location(data['user_id'], data.get('location_id'))
        
        if success:
            return jsonify({
                "status": "success", 
                "message": "Sede asignada correctamente"
            }), 200
        else:
            return jsonify({
                "status": "error", 
                "message": "No se pudo actualizar la base de datos"
            }), 500
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": str(e)
        }), 500