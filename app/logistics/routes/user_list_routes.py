from flask import jsonify, render_template
from app.logistics import logistics_bp
from app.logistics.services.user_list_service import UserListService

@logistics_bp.route('/users/view', methods=['GET'])
def users_page():
    return render_template('logistics/user_list.html')

@logistics_bp.route('/users', methods=['GET'])
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