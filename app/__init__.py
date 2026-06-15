from flask import Flask
from .extensions import db, mail, login_manager 
from .config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app) 

    login_manager.login_view = 'security.login' 
    login_manager.login_message = "Por favor, inicia sesión para acceder al sistema PH."
    login_manager.login_message_category = "info"

    with app.app_context():
        # Importamos y registramos el Blueprint principal de seguridad
        from .security import security_bp
        app.register_blueprint(security_bp, url_prefix='/auth')
        
        # ==========================================================
        # REGISTRO DEL BLUEPRINT DE AUDITORÍA (Ruta Corregida)
        # ==========================================================
        # Como está dentro de la subcarpeta 'routes', añadimos .routes
        from .security.routes.audit_routes import audit_bp
        app.register_blueprint(audit_bp)
        # ==========================================================
        
        from .logistics import logistics_bp
        app.register_blueprint(logistics_bp)
        
        from .logistics import list_sedes_bp, status_location_bp
        app.register_blueprint(list_sedes_bp)
        app.register_blueprint(status_location_bp)
        
        from .logistics.routes.location_routes import location_bp
        app.register_blueprint(location_bp, url_prefix='/logistics')

        # Importamos el Blueprint que acabamos de estructurar arriba
        from .inventory import inventory_bp
        # Lo registramos con el prefijo /inventory para que sea estético y organizado
        app.register_blueprint(inventory_bp, url_prefix='/inventory')

        # ==========================================================
        # MÓDULO 4: REGISTRO DE LA API MULTI-MONEDA (Nueva Carpeta Integrations)
        # ==========================================================
        from .integrations.api_bcv.routes_api import api_bcv_bp
        app.register_blueprint(api_bcv_bp, url_prefix='/bcv')

        from .integrations.imgbb.imgbb_routes import imgbb_bp
        app.register_blueprint(imgbb_bp)
        # ==========================================================

        from . import models 
        from .models.security_model import User
        from app.models import logistics_model
        from app.models import inventory_model
        
        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    print("MIRA AQUÍ ABAJO:")
    print(app.url_map)

    return app