from flask import Blueprint
logistics_bp = Blueprint('logistics', __name__)
list_sedes_bp = Blueprint('list_sedes_bp', __name__)
status_location_bp = Blueprint('status_location_bp', __name__)

from .routes.user_list_routes import logistics_users_bp
from .routes import list_locations_route
from .routes import status_location_route
logistics_bp.register_blueprint(logistics_users_bp)