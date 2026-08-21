from app.models import Movement # Asegúrate de importar tus modelos correctamente
from app.extensions import db

def get_operational_movements_for_user(user_location_ids):
    """
    Extrae únicamente los traslados en flujo operativo normal ('EN_TRANSITO' y 'COMPLETADO').
    Filtra según las sedes a las que pertenece el usuario.
    """
    return Movement.query.filter(
        Movement.status.in_(['EN_TRANSITO', 'COMPLETADO']),
        (Movement.origin_location_id.in_(user_location_ids)) | 
        (Movement.destination_location_id.in_(user_location_ids))
    ).order_by(Movement.date.desc()).all()