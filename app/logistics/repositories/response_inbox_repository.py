from app.models import Movement, Location
from sqlalchemy import or_

class ResponseInboxRepository:
    @staticmethod
    def get_admin_responses(user):
        # Estados que indican que el Administrador ya emitió una respuesta/dictamen
        resolved_statuses = [
            'RESOLUCION_REINTEGRO', 
            'RESOLUCION_BAJA_EXTRAVIO', 
            'RETORNO_EMERGENCIA_LIQUIDACION',
            'CERRADO_POR_ADMIN',
            'CERRADO_CON_PERDIDA'
        ]
        
        query = Movement.query.filter(Movement.status.in_(resolved_statuses))
        
        if not (user.is_admin or user.is_finance):
            location_ids = [loc.id for loc in user.locations]
            query = query.filter(
                or_(
                    Movement.origin_location_id.in_(location_ids),
                    Movement.destination_location_id.in_(location_ids)
                )
            )
            
        movements = query.order_by(Movement.date.desc()).all()

        # Vinculación dinámica en memoria (evita modificar el archivo del modelo)
        locations = Location.query.all()
        loc_map = {loc.id: loc for loc in locations}

        for mov in movements:
            mov.origin_location = loc_map.get(mov.origin_location_id)
            mov.destination_location = loc_map.get(mov.destination_location_id)

        return movements