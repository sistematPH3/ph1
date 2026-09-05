class WasteConfigValidationError(Exception):
    """Excepción personalizada para errores de validación en configuración de mermas."""
    pass


class WasteConfigValidators:

    @staticmethod
    def validate_admin_permission(role_id: int, admin_role_id: int = 1):
        if role_id is None or int(role_id) != admin_role_id:
            raise WasteConfigValidationError("Acceso denegado: Se requieren privilegios de Administrador para esta acción.")

    @staticmethod
    def validate_waste_config_data(data: dict):
        if not isinstance(data, dict):
            raise WasteConfigValidationError("Los datos de configuración deben ser un objeto JSON válido.")

    @staticmethod
    def validate_config_data(data: dict) -> dict:
        errors = {}
        if not isinstance(data, dict):
            return {'data': 'Los datos de entrada deben ser un diccionario.'}

        if 'WASTE_TIME_TOLERANCE' in data:
            try:
                val = float(data['WASTE_TIME_TOLERANCE'])
                # La tolerancia mínima debe ser 1.00 (factor base)
                if val < 1.0:
                    errors['WASTE_TIME_TOLERANCE'] = "El factor de tolerancia debe ser mayor o igual a 1.00."
            except (ValueError, TypeError):
                errors['WASTE_TIME_TOLERANCE'] = "Debe ser un valor numérico válido."

        if 'WASTE_BASE_PERIOD_DAYS' in data:
            try:
                val = int(data['WASTE_BASE_PERIOD_DAYS'])
                # Los días deben ser mayores a 0 (y opcionalmente max 90 según la UI)
                if val <= 0:
                    errors['WASTE_BASE_PERIOD_DAYS'] = "Los días base deben ser un entero mayor a 0."
                elif val > 90:
                    errors['WASTE_BASE_PERIOD_DAYS'] = "Los días base no pueden exceder los 90 días."
            except (ValueError, TypeError):
                errors['WASTE_BASE_PERIOD_DAYS'] = "Debe ser un número entero válido."

        return errors