from flask import Blueprint

# 1. Creamos el Blueprint exclusivo para el módulo de inventario.
# Definimos el prefijo de plantillas para apuntar a la subcarpeta dentro de templates.
inventory_bp = Blueprint(
    'inventory', 
    __name__, 
    template_folder='../templates/inventory',
    static_folder='../static'
)

# 2. Al final, importamos el archivo de rutas para que Flask registre los endpoints.
# Lo hacemos aquí abajo para evitar importaciones circulares.
from app.inventory.routes import list_product_routes
from app.inventory.routes import products_routes #DE leminyer
from app.inventory.routes import categories_routes
from app.inventory.routes import inventory_views_routes
