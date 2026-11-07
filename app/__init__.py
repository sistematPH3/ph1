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
        # ----------------------------------------------------------
        # REGISTRO DE BLUEPRINTS (MÓDULO 1: SEGURIDAD Y AUDITORÍA)
        # ----------------------------------------------------------
        from .security import security_bp
        app.register_blueprint(security_bp, url_prefix='/auth')

        # Registro del Blueprint de Auditoría (Ruta Corregida)
        from .security.routes.audit_routes import audit_bp
        app.register_blueprint(audit_bp)
        # ----------------------------------------------------------

        from . import models 
        from .models.security_model import User
        
        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    return app