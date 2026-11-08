from app import db
from app.models.logistics_model import Location

class StatusLocationsRepository:
    @staticmethod
    def update_status(location_id, new_status):
        # Actualiza el campo is_active
        location = Location.query.get(location_id)
        if location:
            location.is_active = new_status
            
            # --- NUEVO: Sincronización automática ---
            # Si estamos desactivando la sede, forzamos la actualización de los usuarios
            if not new_status:
                for usuario in location.assigned_users:
                    usuario.sync_activation_status()
            
            db.session.commit()
        return location