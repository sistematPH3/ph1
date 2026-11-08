from app.models import Location

def get_location_details(location_id):
    """
    Consulta los detalles y separa el estado de la dirección para la UI.
    """
    location = Location.query.get(location_id)
    if not location:
        return None

    return {
        "id": location.id,
        "name": location.name,
        "state": location.state,              # <--- Leemos directo de la columna state
        "detailed_address": location.detailed_address, # <--- Leemos directo de detailed_address
        "phone": location.phone,
        "is_active": location.is_active
    }