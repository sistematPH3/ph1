from app.extensions import db
from app.models import Location 

def register_location_service(form_data):
    """
    Lógica para registrar una sede sin alterar la BD.
    Concatena el estado con la dirección.
    """
    try:
        
        full_address = f"{form_data.state.data} - {form_data.address.data}"
        
        new_location = Location(
            name=form_data.name.data,
            address=full_address,
            phone=form_data.phone.data,
            is_active=True
        )
        
        db.session.add(new_location)
        db.session.commit()
        return True, "Sede registrada exitosamente."
    except Exception as e:
        db.session.rollback()
        return False, f"Error al registrar: {str(e)}"