# app/logistics/routes/user_routes.py
from flask import Blueprint, jsonify
from app.logistics.services.user_list_service import UserService

# Creamos el blueprint para las rutas de usuarios en logística
logistics_users_bp = Blueprint('logistics_users', __name__)

@logistics_users_bp.route('/users', methods=['GET'])
def list_users():
    try:
        users = UserService.get_users_list()
        return jsonify({
            "status": "success",
            "data": users
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Ocurrió un error al obtener el listado de usuarios.",
            "details": str(e)
        }), 500