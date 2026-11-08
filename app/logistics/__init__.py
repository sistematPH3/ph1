# app/logistics/__init__.py
from flask import Blueprint
from .routes.movement_dispatch_routes import dispatch_bp

# 1. Se crean los Blueprints principales del módulo de logística
logistics_bp = Blueprint('logistics', __name__)
list_sedes_bp = Blueprint('list_sedes_bp', __name__)
status_location_bp = Blueprint('status_location_bp', __name__)

# 2. Importaciones de las rutas de tus compañeros
from .routes import list_locations_route
from .routes import status_location_route

# 3. Importación de TU submódulo de historial y el NUEVO de proveedores
from .routes.purchase_management_routes import purchase_management_bp
from .routes.supplier_routes import suppliers_bp  # <--- Tu nueva ruta en inglés

# 4. Registro de los sub-blueprints dentro del principal de logística
logistics_bp.register_blueprint(purchase_management_bp)
logistics_bp.register_blueprint(suppliers_bp)
logistics_bp.register_blueprint(dispatch_bp, url_prefix='/logistics/movements')
