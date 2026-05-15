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
        from .security import security_bp
        app.register_blueprint(security_bp, url_prefix='/auth')
        
        from .logistics import logistics_bp
        app.register_blueprint(logistics_bp)
        
        from .logistics import list_sedes_bp, status_location_bp
        app.register_blueprint(list_sedes_bp)
        app.register_blueprint(status_location_bp)
        
        from .logistics.routes.location_routes import location_bp
        app.register_blueprint(location_bp, url_prefix='/logistics', name='location_routes_bp')

        from . import models 
        from .models.security_model import User
        
        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    print("MIRA AQUÍ ABAJO:")
    print(app.url_map)

    return app