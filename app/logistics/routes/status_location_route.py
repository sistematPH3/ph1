from flask import request, redirect, url_for, flash
from app import db
from app.models.logistics_model import Location
from app.decorators.roles import admin_required
from .. import status_location_bp 
from ..services.status_location_service import StatusLocationService

@status_location_bp.route('/sedes/status/<int:id>', methods=['POST'])
@admin_required
def change_status(id):
    location = Location.query.get_or_404(id)
    
    # Leemos el valor del input hidden
    current_status = request.form.get('current_status') == 'true'
    
    try:
        # 1. Llamamos al servicio (aquí se ejecuta la validación de disputas/traslados)
        StatusLocationService.toggle_location_status(location.id, current_status)
        
        # 2. Si pasa la validación, procedemos con la sincronización de usuarios
        if current_status:  # Se está desactivando
            for usuario in location.assigned_users:
                usuario.sync_activation_status()
            flash(f"La sede {location.name} ha sido desactivada y los usuarios vinculados fueron validados.", "warning")
        else:  # Se está activando
            for usuario in location.assigned_users:
                usuario.sync_activation_status()
            flash(f"La sede {location.name} ha sido activada y los usuarios vinculados fueron validados.", "success")
        
        db.session.commit()
        print(f"DEBUG: Sede {id} cambiada a {not current_status}")

    except ValueError as e:
        # Atrapa la excepción de validate_location_can_be_deactivated y cancela el cambio
        db.session.rollback()
        flash(str(e), "danger")

    except Exception as e:
        db.session.rollback()
        flash(f"Error inesperado al cambiar el estado de la sede: {str(e)}", "danger")
    
    return redirect(url_for('list_sedes_bp.list_sedes'))