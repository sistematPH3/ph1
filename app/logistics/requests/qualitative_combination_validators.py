"""Combinaciones cualitativas mixtas permitidas por renglón (recepción y arbitraje).

Un mismo renglón puede presentar simultáneamente dos incidencias de calidad.
El sistema solo admite las cuatro duplas aprobadas por operación:

    1. LOTE_NO_COINCIDE       + INCIDENCIA_TEMPERATURA
    2. VENCIMIENTO_PROXIMO    + INCIDENCIA_TEMPERATURA
    3. LOTE_NO_COINCIDE       + VIOLACION_CUSTODIA
    4. VENCIMIENTO_PROXIMO    + LOTE_NO_COINCIDE

La condición principal se sigue guardando en ``item_condition`` (y en el
estado del movimiento). La secundaria viaja en el JSON de auditoría de la
recepción (``secondary_condition``), de modo que no se altera el esquema de
base de datos.

Este módulo es la fuente única de verdad para validadores, servicios y
plantillas: evita que la interfaz ofrezca combinaciones o resoluciones que el
backend no reconoce.
"""

# Condiciones que describen calidad/estado y pueden combinarse entre sí.
QUALITATIVE_ITEM_CONDITIONS = (
    'LOTE_NO_COINCIDE',
    'VENCIMIENTO_PROXIMO',
    'INCIDENCIA_TEMPERATURA',
    'VIOLACION_CUSTODIA',
)

# Acciones de resolución. Se listan en orden de la MÁS restrictiva a la menos
# restrictiva: la primera opción es la que el operador ve primero en la UI.
_RETURN_AND_WRITE_OFF = (
    {
        'code': 'RETORNO_EMERGENCIA',
        'label': 'Devolver al central (retorno de emergencia)',
        'requires_lot': False,
        'restrictive': True,
    },
    {
        'code': 'DERIVAR_MERMA_SANITARIA',
        'label': 'Derivar a merma sanitaria (descarte total del renglón)',
        'requires_lot': False,
        'restrictive': True,
    },
)

QUALITATIVE_COMBINATIONS = {
    frozenset(('LOTE_NO_COINCIDE', 'INCIDENCIA_TEMPERATURA')): {
        'label': 'Lote no coincide con Guía + Ruptura de Cadena de Frío',
        'options': _RETURN_AND_WRITE_OFF,
    },
    frozenset(('VENCIMIENTO_PROXIMO', 'INCIDENCIA_TEMPERATURA')): {
        'label': 'Vencimiento Próximo + Ruptura de Cadena de Frío',
        'options': _RETURN_AND_WRITE_OFF,
    },
    frozenset(('LOTE_NO_COINCIDE', 'VIOLACION_CUSTODIA')): {
        'label': 'Lote no coincide con Guía + Violación de Custodia',
        'options': _RETURN_AND_WRITE_OFF,
    },
    frozenset(('VENCIMIENTO_PROXIMO', 'LOTE_NO_COINCIDE')): {
        'label': 'Vencimiento Próximo + Lote no coincide con Guía',
        # La corrección administrativa del lote no resuelve el riesgo de
        # vencimiento: solo se ofrece después de las salidas restrictivas.
        'options': _RETURN_AND_WRITE_OFF + (
            {
                'code': 'CORREGIR_LOTE',
                'label': 'Actualizar y corregir número de lote (con alerta FEFO)',
                'requires_lot': True,
                'restrictive': False,
            },
        ),
    },
}


def normalize_combination(primary_condition, secondary_condition):
    """Clave normalizada (sin orden) de la dupla, o None si falta una condición."""
    if not primary_condition or not secondary_condition:
        return None
    return frozenset((primary_condition, secondary_condition))


def is_qualitative_condition(condition):
    """True si la condición es de calidad/estado (combinable)."""
    return condition in QUALITATIVE_ITEM_CONDITIONS


def is_allowed_combination(primary_condition, secondary_condition):
    """True si la dupla es una de las cuatro combinaciones aprobadas."""
    key = normalize_combination(primary_condition, secondary_condition)
    return key in QUALITATIVE_COMBINATIONS


def get_combination(primary_condition, secondary_condition):
    """Devuelve la definición de la dupla aprobada, o None."""
    key = normalize_combination(primary_condition, secondary_condition)
    return QUALITATIVE_COMBINATIONS.get(key)


def get_combination_label(primary_condition, secondary_condition):
    """Etiqueta legible de la dupla, o None si no es una combinación aprobada."""
    combination = get_combination(primary_condition, secondary_condition)
    return combination['label'] if combination else None


def get_combination_options(primary_condition, secondary_condition):
    """Opciones de resolución ordenadas para la dupla (lista vacía si no aplica)."""
    combination = get_combination(primary_condition, secondary_condition)
    return list(combination['options']) if combination else []


def get_allowed_actions(primary_condition, secondary_condition):
    """Códigos de acción permitidos para la dupla; None si no hay dupla."""
    combination = get_combination(primary_condition, secondary_condition)
    if not combination:
        return None
    return [option['code'] for option in combination['options']]


def is_allowed_combination_action(primary_condition, secondary_condition, action):
    """True si la acción respeta la matriz restrictiva de la dupla.

    Cuando el renglón no declara una dupla aprobada no se restringe aquí (cada
    condición individual conserva sus reglas históricas).
    """
    allowed = get_allowed_actions(primary_condition, secondary_condition)
    if allowed is None:
        return True
    return action in allowed


def combination_requires_lot(primary_condition, secondary_condition):
    """True si la dupla involucra un lote distinto al de la guía."""
    key = normalize_combination(primary_condition, secondary_condition)
    if key is None:
        return False
    return 'LOTE_NO_COINCIDE' in key


def combination_has_critical_risk(primary_condition, secondary_condition):
    """True si la dupla incluye temperatura o custodia (riesgo sanitario/legal)."""
    key = normalize_combination(primary_condition, secondary_condition)
    if key is None:
        return False
    return bool(key & {'INCIDENCIA_TEMPERATURA', 'VIOLACION_CUSTODIA'})
