# app/logistics/validators/movement_dispute_validators.py

from app.logistics.requests.qualitative_combination_validators import (
    get_allowed_actions,
    get_combination_label,
    is_allowed_combination,
)


class MovementDisputeValidator:
    """
    Validador con 's' (movement_dispute_validators) — valida el payload del
    formulario de resolución GRANULAR (item por item) que llega desde
    movement_dispute.html / resolveModal-{id}.
    """

    ALLOWED_ACTIONS = [
        'ACEPTAR_RECEPCION',
        'BAJA_EXTRAVIO_PARCIAL',
        'RESOLUCION_REINTEGRO',
        'RESOLUCION_ACREDITAR_DESTINO',
        'DERIVAR_MERMA_SANITARIA',
        'RECEPCION_CONFORME_FEFO',
        'CORREGIR_LOTE',
        'RETORNO_EMERGENCIA',
        'INCIDENCIA_INTERNA',
    ]

    @staticmethod
    def validate_combination_action(primary_condition, secondary_condition, action_type):
        """Valida la acción elegida contra la matriz de una dupla cualitativa.

        Devuelve (True, None) cuando el renglón no declara una combinación
        aprobada o cuando la acción respeta la matriz. En caso contrario
        devuelve (False, mensaje) para que el servicio rechace la resolución.
        """
        if not is_allowed_combination(primary_condition, secondary_condition):
            return True, None
        allowed_actions = get_allowed_actions(primary_condition, secondary_condition)
        if action_type in allowed_actions:
            return True, None
        return False, (
            f"La combinación '{get_combination_label(primary_condition, secondary_condition)}' "
            "prioriza la acción más restrictiva: solo admite "
            f"{', '.join(allowed_actions)}. "
            "No puede resolverse con una acción menos restrictiva."
        )

    @staticmethod
    def validate_resolution_payload(form_data, movement):
        errors = []

        if form_data is None:
            return False, ["No se recibieron datos del formulario de resolución."]

        general_notes = (form_data.get('general_notes') or '').strip()
        if len(general_notes) < 15:
            errors.append("El acta y justificación legal general es obligatoria y debe contener al menos 15 caracteres.")

        details = getattr(movement, 'details', None) or []
        if not details:
            errors.append("El traslado no posee ítems de detalle para resolver.")

        items_resolutions = {}

        for detail in details:
            action_key = f"item_{detail.id}_action"
            lot_key = f"item_{detail.id}_lot"
            replenish_key = f"item_{detail.id}_replenish"

            action_type = form_data.get(action_key)

            if not action_type or action_type not in MovementDisputeValidator.ALLOWED_ACTIONS:
                errors.append(f"Ítem #{detail.id}: Debe seleccionar una acción de resolución válida.")
                continue

            lot_number = (form_data.get(lot_key) or '').strip() or None

            if action_type == 'CORREGIR_LOTE' and not lot_number:
                errors.append(f"Ítem #{detail.id}: Debe especificar el nuevo número de lote real.")
                continue

            items_resolutions[str(detail.id)] = {
                'action_type': action_type,
                'lot_number': lot_number,
                'generate_replenishment': form_data.get(replenish_key) in ('on', 'true', '1', True)
            }

        if errors:
            return False, errors

        return True, {
            'items_resolutions': items_resolutions,
            'general_notes': general_notes
        }