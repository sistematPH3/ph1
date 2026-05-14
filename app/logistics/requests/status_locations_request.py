from flask import flash

class StatusLocationsRequest:
    def __init__(self, location_id, current_status):
        self.location_id = location_id
        self.current_status = current_status

    def validate(self):
        # Valida que el ID sea un número entero positivo
        if not isinstance(self.location_id, int) or self.location_id <= 0:
            flash("ID de sede inválido.", "danger")
            return False
        return True