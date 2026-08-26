from ..repositories.status_locations_repository import StatusLocationsRepository
from app.logistics.services.movement_dispute_service import MovementDisputeService

class StatusLocationService:
    @staticmethod
    def toggle_location_status(location_id, current_status):
        # El servicio calcula el nuevo estado de manera limpia
        new_status = not current_status
        
        # Si se va a DESACTIVAR la sede (new_status es False),
        # ejecutamos la validación del candado de logística
        if not new_status:
            MovementDisputeService.validate_location_can_be_deactivated(location_id)
        
        # Si pasa la validación (o si se está activando), actualizamos el estado
        return StatusLocationsRepository.update_status(location_id, new_status)