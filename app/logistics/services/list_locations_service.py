from ..repositories.list_locations_repository import ListLocationsRepository

class ListLocationsService:
    @staticmethod
    def list_all_locations():
        return ListLocationsRepository.get_all()