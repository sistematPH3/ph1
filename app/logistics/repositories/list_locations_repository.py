from app import db
from app.models import Location # Asumiendo que tu modelo se llama Location

class ListLocationsRepository:
    @staticmethod
    def get_all():
        # Trae todas las sedes de la tabla public.locations
        return Location.query.all()