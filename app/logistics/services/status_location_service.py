from ..repositories.status_locations_repository import StatusLocationsRepository

class StatusLocationService:
    @staticmethod
    def toggle_location_status(location_id, current_status):
        # El servicio calcula el nuevo estado de manera limpia
        new_status = not current_status
        
        # Llamamos al repositorio que ya hemos configurado 
        # para que maneje la sincronización de usuarios (sync_activation_status)
        return StatusLocationsRepository.update_status(location_id, new_status)