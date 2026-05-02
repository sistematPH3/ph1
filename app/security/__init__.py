from flask import Blueprint


security_bp = Blueprint('security', __name__, template_folder='templates')


from .routes import login_routes    
#from .routes import register_routes  
from .routes import token_routes     