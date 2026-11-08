from flask import Blueprint


security_bp = Blueprint('security', __name__)


 
from .routes import login_routes
from .routes import register_routes
from .routes import token_routes
from .routes import user_management_routes
