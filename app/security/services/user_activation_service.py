import logging

logger = logging.getLogger(__name__)


class UserActivationService:
    """Reglas de activación automática por asignación de sedes.

    `User.sync_activation_status()` (modelo) solo desactiva a quien se queda sin
    sedes activas y deja intacto el `is_active` del resto, para no revertir una
    desactivación manual del administrador. Eso dejaba inactivo al usuario nuevo
    que, al aprobarse, recibía rol y sedes activas: había que activarlo a mano.

    Aquí se cubre únicamente el alta inicial: usuario inactivo que nunca tuvo
    sedes y que recibe por primera vez al menos una sede activa. Un usuario que
    ya tenía sedes (aunque se haya desactivado a mano) no se reactiva.
    """

    @staticmethod
    def es_alta_inicial_con_sedes_activas(usuario, sedes_previas):
        if usuario is None or usuario.is_active:
            return False

        # Administradores e invitados se rigen por las reglas especiales de
        # sync_activation_status / del flujo de aprobación.
        if usuario.is_admin or usuario.is_guest:
            return False

        # Ya contaba con sedes: su estado lo controla el administrador.
        if sedes_previas:
            return False

        return any(loc.is_active for loc in usuario.locations)

    @staticmethod
    def activar_en_alta_inicial(usuario, sedes_previas):
        """Activa al usuario recién dotado de sedes activas. Devuelve True si cambió."""
        if not UserActivationService.es_alta_inicial_con_sedes_activas(usuario, sedes_previas):
            return False

        usuario.is_active = True
        logger.info(
            "Usuario %s activado automáticamente al recibir sus primeras sedes activas",
            getattr(usuario, "id", "?"),
        )
        return True
