from app.models import Location

def get_location_details(location_id):
    """
    Consulta los detalles y separa el estado de la dirección para la UI.
    """
    location = Location.query.get(location_id)
    if not location:
        return None

    parts = location.address.split(" - ", 1)
    state = parts[0] if len(parts) > 1 else "No definido"
    address_detail = parts[1] if len(parts) > 1 else location.address

    return {
        "id": location.id,
        "name": location.name,
        "state": state,
        "address": address_detail,
        "phone": location.phone,
        "is_active": location.is_active
    }