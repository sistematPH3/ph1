from flask import Flask
from .extensions import db, mail, login_manager 
from .config import Config
from .security import security_bp

# --- UNIFICACIÓN DE IMPORTACIONES ---
# Tus Blueprints de logística
from .logistics import list_sedes_bp, status_location_bp
# El Blueprint que agregó Diego (ajustado a importación relativa para evitar errores)
from .logistics.routes.location_routes import location_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Extensiones
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app) 

    login_manager.login_view = 'security.login' 
    login_manager.login_message = "Por favor, inicia sesión para acceder al sistema PH."
    login_manager.login_message_category = "info"

    # --- REGISTRO DE BLUEPRINTS (LO TUYO + LO DE DIEGO) ---
    
    # 1. Seguridad (Ambos lo tenían igual)
    app.register_blueprint(security_bp, url_prefix='/auth')
    
    # 2. Tu parte: Sedes y Estatus
    app.register_blueprint(list_sedes_bp)
    app.register_blueprint(status_location_bp)
    
    # 3. La parte de Diego: Location Routes con su prefijo
    app.register_blueprint(location_bp, url_prefix='/logistics')

    with app.app_context():
        from . import models 
        from .models.security_model import User
        
        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    return app
