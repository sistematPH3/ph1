# app/logistics/services/update_location.py
from app.extensions import db
from app.models import Location

def update_location_service(location_id, form_data):
    try:
        location = Location.query.get(location_id)
        if not location:
            return False, "La sede no existe."

        # Concatenamos igual que en el registro
        full_address = f"{form_data.state.data} - {form_data.address.data}"
        
        location.name = form_data.name.data
        location.address = full_address
        location.phone = form_data.phone.data
        
        db.session.commit()
        return True, "Sede actualizada correctamente."
    except Exception as e:
        db.session.rollback()
        return False, f"Error al actualizar: {str(e)}"