from flask import flash

class UserManagementValidator:
    @staticmethod
    def validate_approval(user_id, role_id):
        """Revisa que los datos de aprobación sean lógicos."""
        if not user_id or not role_id:
            flash("Faltan datos obligatorios para la aprobación.", "danger")
            return False
        
        if int(role_id) <= 0:
            flash("Debes asignar un rol válido (mayor a 0).", "warning")
            return False
            
        return True