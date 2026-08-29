from app.models import Movement 
from app.extensions import db

def get_operational_movements_for_user(user_location_ids):
    """
    Extrae únicamente los traslados en flujo operativo normal, incluyendo discrepancias.
    Filtra según las sedes a las que pertenece el usuario.
    """
    return Movement.query.filter(
        Movement.status.in_(['EN_TRANSITO', 'COMPLETADO', 'EN_ARBITRAJE']),
        (Movement.origin_location_id.in_(user_location_ids)) | 
        (Movement.destination_location_id.in_(user_location_ids))
    ).order_by(Movement.date.desc()).all()