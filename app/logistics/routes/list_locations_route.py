from flask import render_template
from .. import list_sedes_bp # Importa el objeto desde app/logistics/__init__.py
from app.models import Location  # Asegúrate de que tu modelo se llame Location

@list_sedes_bp.route('/sedes')
def list_sedes():
    # 1. Consultamos todos los registros de la tabla 'locations'
    locations = Location.query.all()
    
    # 2. Imprimimos en la terminal para depurar (Debug)
    # Esto te permite ver si la lista viene vacía o con datos
    print("-" * 30)
    print(f"DEBUG: Se encontraron {len(locations)} sedes en la base de datos.")
    for loc in locations:
        print(f"ID: {loc.id} | Nombre: {loc.name} | Estatus: {loc.is_active}")
    print("-" * 30)
    
    # 3. Enviamos los datos al HTML
    return render_template('logistics/list_locations.html', locations=locations)