from app.extensions import db
from app.models import Location 

def register_location_service(form_data):
    """
    Lógica para registrar una sede guardando los datos estructurados en la BD.
    """
    try:
        # ELIMINAMOS la variable full_address
        
        new_location = Location(
            name=form_data.name.data,
            state=form_data.state.data,              # Se guarda directo en su columna
            detailed_address=form_data.address.data, # El campo 'address' del formulario va a 'detailed_address'
            phone=form_data.phone.data,
            is_active=True
        )
        
        db.session.add(new_location)
        db.session.commit()
        return True, "Sede registrada exitosamente."
    except Exception as e:
        db.session.rollback()
        return False, f"Error al registrar: {str(e)}"