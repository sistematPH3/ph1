from ..repositories.status_locations_repository import StatusLocationsRepository

class StatusLocationService:
    @staticmethod
    def toggle_location_status(location_id, current_status):
        # Si está activa (True), la desactiva (False) y viceversa
        new_status = not current_status
        return StatusLocationsRepository.update_status(location_id, new_status)