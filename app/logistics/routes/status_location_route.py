from flask import request, redirect, url_for
from app import db
from app.models import Location
# IMPORTANTE: Esta línea es la que falta
from .. import status_location_bp 

@status_location_bp.route('/sedes/status/<int:id>', methods=['POST'])
def change_status(id):
    location = Location.query.get_or_404(id)
    
    # Leemos el valor del input hidden que pusimos en el HTML
    current_status = request.form.get('current_status')
    
    # Cambiamos el estado (si era true, pasa a False)
    if current_status == 'true':
        location.is_active = False
    else:
        location.is_active = True
    
    db.session.commit()
    
    print(f"DEBUG: Sede {id} cambiada a {location.is_active}")
    
    # Redirigir a la lista de sedes
    return redirect(url_for('list_sedes_bp.list_sedes'))