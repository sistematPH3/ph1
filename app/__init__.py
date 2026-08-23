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

        # ==========================================================
        # REGISTRO DEL BLUEPRINT DE AUDITORÍA DE PERSONAL (NUEVO)
        # ==========================================================
        from .security.routes.audit_user_routes import audit_user_bp
        app.register_blueprint(audit_user_bp)
        # ==========================================================

        # ==========================================================
        # REGISTRO DEL BLUEPRINT DE AUDITORÍA DE COMPRAS
        # ==========================================================
        from .security.routes.audit_purchase_routes import audit_purchase_bp
        app.register_blueprint(audit_purchase_bp)
        # ==========================================================

        # ==========================================================
        # MÓDULO WASTE: AUDITORÍA DE INVENTARIO 
        # ==========================================================
        from .waste.routes.auditinventory_routes import auditinventory_bp
        app.register_blueprint(auditinventory_bp)
        # ==========================================================
        
        from .logistics import logistics_bp
        app.register_blueprint(logistics_bp)
        
        from .logistics import list_sedes_bp, status_location_bp
        app.register_blueprint(list_sedes_bp)
        app.register_blueprint(status_location_bp)
        
        from .logistics.routes.location_routes import location_bp
        app.register_blueprint(location_bp, url_prefix='/logistics')
        
        # ==========================================================\
        # REGISTRO DEL SUB-MÓDULO DE REGISTRO DE COMPRAS de Modulo 4
        # ==========================================================\
        from .logistics.routes.purchase_routes import purchase_bp
        app.register_blueprint(purchase_bp, url_prefix='/logistics')
        # ==========================================================\

        # ==========================================================\
        # SUB-MÓDULO: LISTADO DE PROVEEDORES (NUEVO)
        # ==========================================================\
        from .logistics.routes.supplier_list_routes import supplier_list_bp
        app.register_blueprint(supplier_list_bp, url_prefix='/logistics')
        # ==========================================================\

        
        from .inventory import inventory_bp
        
        app.register_blueprint(inventory_bp, url_prefix='/inventory')

        # ==========================================================\
        # REGISTRO DE CONSUMO DE COCINA (MÓDULO 5)
        # ==========================================================\
        from .inventory.routes.register_consumption_routes import register_consumption_bp
        app.register_blueprint(register_consumption_bp)
        # ==========================================================\

        # ==========================================================\
        # GESTIÓN DE COMPRAS 
        # ==========================================================\
        from .logistics.routes.purchase_management_routes import purchase_management_bp
        app.register_blueprint(purchase_management_bp, url_prefix='/logistics')
        # ==========================================================\

        # ==========================================================
        # MÓDULO 4: REGISTRO DE LA API MULTI-MONEDA (Nueva Carpeta Integrations)
        # ==========================================================
        from .integrations.api_bcv.routes_api import api_bcv_bp
        app.register_blueprint(api_bcv_bp, url_prefix='/bcv')

        from .integrations.imgbb.imgbb_routes import imgbb_bp
        app.register_blueprint(imgbb_bp)
        # ==========================================================

        from app.dashboard.dashboard_routes import dashboard_bp
        app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

       # ==========================================================
        # MÓDULO: PERSONAL (STAFF)
        # ==========================================================
        from app.security.routes.staff_routes import staff_bp
        app.register_blueprint(staff_bp, url_prefix='/staff')

        from app.inventory.routes.inventory_movement_routes import inventory_movements_bp
        app.register_blueprint(inventory_movements_bp)

        from app.logistics.routes.movement_list_routes import logistics_list_bp
        app.register_blueprint(logistics_list_bp)

        from app.logistics.routes.movement_dispute_routes import movement_dispute_bp
        app.register_blueprint(movement_dispute_bp)

        # ==========================================================
        # MÓDULO 6
        # ==========================================================
        from app.logistics.routes.movement_reception_routes import movement_reception_bp
        app.register_blueprint(movement_reception_bp)
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