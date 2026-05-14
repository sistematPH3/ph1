from flask import Blueprint

# 1. Definir los Blueprints
list_sedes_bp = Blueprint('list_sedes_bp', __name__)
status_location_bp = Blueprint('status_location_bp', __name__)

# 2. IMPORTAR LAS RUTAS (Esto es lo que te falta para que aparezcan en la lista)
from .routes import list_locations_route
from .routes import status_location_route