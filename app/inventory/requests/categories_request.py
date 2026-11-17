"""Reglas de vencimiento de las categorías (ProductType).

La configuración de vencimiento pertenece exclusivamente a la categoría:

  - 'manual': la fecha se digita en cada compra (requires_manual_date=True,
    sin días fijos).
  - 'days':   la fecha se autocalcula con los días de vida útil estándar
    (requires_manual_date=False, shelf_life_days entero >= 1).

El formulario de productos/insumos NO maneja vencimientos: solo hereda la
regla de la categoría seleccionada.
"""

VALID_CONTROLS = ('manual', 'days')


def validate_expiration_control(data):
    """Valida la regla de vencimiento recibida en un formulario de categoría.

    Devuelve ``(errors, requires_manual_date, shelf_life_days)``. Si la regla
    no es válida, ``errors`` contiene las claves ``expiration_control`` y/o
    ``shelf_life_days`` y los valores de negocio quedan en ``None``.
    """
    errors = {}
    control = str(data.get('expiration_control') or '').strip().lower()

    if control == 'manual':
        return errors, True, None

    if control == 'days':
        raw_days = data.get('shelf_life_days')
        raw_days = '' if raw_days is None else str(raw_days).strip()
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = None
        if days is None or days < 1:
            errors['shelf_life_days'] = (
                'Debe indicar los días de vida útil: un número entero mayor o igual a 1.'
            )
            return errors, None, None
        return errors, False, days

    errors['expiration_control'] = (
        'Debe seleccionar la regla de vencimiento: fecha manual en compra '
        'o días de vida útil estándar.'
    )
    return errors, None, None
