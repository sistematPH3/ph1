"""Helpers de ubicación para la Auditoría de Accesos.

Viven fuera de ``app/models`` para que ``LoginAudit`` no cargue lógica de
presentación. Se exponen como filtros Jinja en ``create_app`` y los usa
también la exportación PDF/Excel.
"""

UBICACION_CENTRAL_LABEL = 'Almacén Central'
UBICACION_INVITADOS_LABEL = 'Pantalla de Invitados'
UBICACION_CENTRAL_KEY = 'central_warehouse'
UBICACION_INVITADOS_KEY = 'guest_screen'

# `roles.id` 1 es el Administrador en el seed de fábrica. Se usa solo como
# respaldo cuando el registro no trae el nombre del rol cargado.
ROL_ADMINISTRADOR_ID = 1
ROLES_ADMINISTRADOR = ('administrator', 'admin')


def es_acceso_invitado(log):
    """True si el acceso corresponde a un invitado (rol Guest / role_id 0)."""
    if getattr(log, 'role_id', None) == 0:
        return True
    rol = getattr(log, 'role', None)
    if rol is not None and (getattr(rol, 'name', '') or '').lower() == 'guest':
        return True
    usuario = getattr(log, 'user', None)
    return bool(usuario is not None and getattr(usuario, 'is_guest', False))


def es_acceso_administrador(log):
    """True si el acceso pertenece a un administrador.

    Se reconoce por cualquiera de las tres vías disponibles, porque el log
    puede venir sin la relación ``role`` cargada (o con ``location_id``
    apuntando a una sede ya inexistente):

    - ``log.user.is_admin`` (rol de la cuenta),
    - nombre del rol del acceso o de la cuenta,
    - ``role_id`` 1, id del rol Administrator en el seed.
    """
    if es_acceso_invitado(log):
        return False

    usuario = getattr(log, 'user', None)
    if usuario is not None and getattr(usuario, 'is_admin', False):
        return True

    nombres = []
    for rol in (getattr(log, 'role', None),
                getattr(usuario, 'role', None) if usuario is not None else None):
        if rol is not None:
            nombres.append((getattr(rol, 'name', '') or '').lower())
    if any(nombre in ROLES_ADMINISTRADOR for nombre in nombres):
        return True

    return getattr(log, 'role_id', None) == ROL_ADMINISTRADOR_ID


def etiqueta_ubicacion(log):
    """Etiqueta visible de la ubicación del acceso.

    - Invitado: 'Pantalla de Invitados'.
    - Administrador: 'Almacén Central' incondicionalmente. El admin opera en
      la ubicación lógica central aunque su ``location_id`` sea nulo, apunte a
      una sede borrada o traiga una sede física asignada.
    - Personal con sede: el nombre de su sede.
    - Personal sin sede: 'Almacén Central' (almacén general).
    """
    if es_acceso_invitado(log):
        return UBICACION_INVITADOS_LABEL
    if es_acceso_administrador(log):
        return UBICACION_CENTRAL_LABEL

    location = getattr(log, 'location', None)
    if location is not None and location.name:
        return location.name
    return UBICACION_CENTRAL_LABEL


def clave_filtro_ubicacion(log):
    """Clave usada por el filtro de sede (coincide con el value del select)."""
    if es_acceso_invitado(log):
        return UBICACION_INVITADOS_KEY
    if es_acceso_administrador(log):
        return UBICACION_CENTRAL_KEY

    sede_id = getattr(log, 'location_id', None)
    location = getattr(log, 'location', None)
    if sede_id is None and location is not None:
        sede_id = location.id
    if sede_id is None:
        return UBICACION_CENTRAL_KEY
    if (location is not None
            and location.name == UBICACION_CENTRAL_LABEL):
        return UBICACION_CENTRAL_KEY
    return str(sede_id)
