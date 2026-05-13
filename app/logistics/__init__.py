from flask import Blueprint
from .routes.user_list_routes import logistics_users_bp

logistics_bp = Blueprint('logistics', __name__)

logistics_bp.register_blueprint(logistics_users_bp)