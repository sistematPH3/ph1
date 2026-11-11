from app import db
from app.models import Location

class StatusLocationsRepository:
    @staticmethod
    def update_status(location_id, new_status):
        # Actualiza el campo is_active
        location = db.session.get(Location, location_id)
        if location:
            location.is_active = new_status
            db.session.commit()
        return location