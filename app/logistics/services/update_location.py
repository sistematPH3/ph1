# app/logistics/services/update_location.py
import logging

from app.extensions import db
from app.models import Location

logger = logging.getLogger(__name__)


def update_location_service(location_id, form_data):
    try:
        location = db.session.get(Location, location_id)
        if not location:
            return False, "La sede no existe."

        # ELIMINAMOS la línea de full_address
        
        location.name = form_data.name.data
        location.state = form_data.state.data              # Actualiza columna state
        location.detailed_address = form_data.address.data # El input del formulario va a detailed_address
        location.phone = form_data.phone.data
        
        db.session.commit()
        return True, "Sede actualizada correctamente."
    except Exception as e:
        logger.exception("Error al actualizar la sede %s", location_id)
        db.session.rollback()
        return False, f"Error al actualizar: {str(e)}"