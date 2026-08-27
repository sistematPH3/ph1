class MovementDisputeValidator:

    ALLOWED_ACTIONS = [
        'RESOLUCION_REINTEGRO',
        'RESOLUCION_BAJA_EXTRAVIO',
        'RETORNO_EMERGENCIA_LIQUIDACION',
        'RESOLUCION_LEGALIZAR_SOBRANTE'
    ]

    @staticmethod
    def validate_dispute_resolution(action_type, resolution_notes):
        errors = []

        if not action_type or action_type not in MovementDisputeValidator.ALLOWED_ACTIONS:
            errors.append("Debe seleccionar una acción contable válida del catálogo oficial.")

        if not resolution_notes or not isinstance(resolution_notes, str) or len(resolution_notes.strip()) < 15:
            errors.append("El acta y justificación legal es obligatoria y debe contener al menos 15 caracteres.")

        if errors:
            return False, errors

        return True, None