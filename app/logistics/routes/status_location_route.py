from flask import request, redirect, url_for, flash
from app import db
from app.models.logistics_model import Location
from app.decorators.roles import admin_required
from .. import status_location_bp 

@status_location_bp.route('/sedes/status/<int:id>', methods=['POST'])
@admin_required
def change_status(id):
    location = Location.query.get_or_404(id)
    
    # Leemos el valor del input hidden que pusimos en el HTML
    current_status = request.form.get('current_status')
    
    # Cambiamos el estado
    if current_status == 'true':
        location.is_active = False
        
        # --- LÓGICA DE SINCRONIZACIÓN AL DESACTIVAR ---
        for usuario in location.assigned_users:
            usuario.sync_activation_status()
        
        flash(f"La sede {location.name} ha sido desactivada y los usuarios vinculados fueron validados.", "warning")
    else:
        location.is_active = True
        
        # --- LÓGICA DE SINCRONIZACIÓN AL ACTIVAR ---
        # Es necesario validar a los usuarios al activar la sede 
        # para que recuperen el acceso si estaban bloqueados.
        for usuario in location.assigned_users:
            usuario.sync_activation_status()
            
        flash(f"La sede {location.name} ha sido activada y los usuarios vinculados fueron validados.", "success")
    
    # Guardamos los cambios de la sede y el estado de los usuarios
    db.session.commit()
    
    print(f"DEBUG: Sede {id} cambiada a {location.is_active}")
    
    # Redirigir a la lista de sedes
    return redirect(url_for('list_sedes_bp.list_sedes'))