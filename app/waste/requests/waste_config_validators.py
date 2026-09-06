class WasteConfigValidators:

    @staticmethod
    def validate_config_data(data: dict) -> dict:
        errors = {}
        if not isinstance(data, dict):
            return {'data': 'Los datos de entrada deben ser un diccionario.'}

        if 'WASTE_TIME_TOLERANCE' in data:
            try:
                val = float(data['WASTE_TIME_TOLERANCE'])
                # La tolerancia mínima es 1.00 (factor base). Sin tope superior.
                if val < 1.0:
                    errors['WASTE_TIME_TOLERANCE'] = "El factor de tolerancia debe ser mayor o igual a 1.00."
            except (ValueError, TypeError):
                errors['WASTE_TIME_TOLERANCE'] = "Debe ser un valor numérico válido."

        if 'WASTE_BASE_PERIOD_DAYS' in data:
            try:
                val = int(data['WASTE_BASE_PERIOD_DAYS'])
                if val <= 0:
                    errors['WASTE_BASE_PERIOD_DAYS'] = "Los días base deben ser un entero mayor a 0."
                elif val > 90:
                    errors['WASTE_BASE_PERIOD_DAYS'] = "Los días base no pueden exceder los 90 días."
            except (ValueError, TypeError):
                errors['WASTE_BASE_PERIOD_DAYS'] = "Debe ser un número entero válido."

        return errors