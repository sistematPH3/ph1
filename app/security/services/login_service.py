from ..repositories.login_repository import LoginRepository
from werkzeug.security import check_password_hash

class LoginService:
    @staticmethod
    def autenticar(email, password):
        """
        Autentica al usuario y valida motivos de acceso denegado:
        - 'ok': Acceso correcto.
        - 'cuenta_desactivada': Desactivado manualmente por administrador.
        - 'sin_sedes': Usuario sin sedes activas.
        - 'correo_no_registrado': El correo no pertenece a ningún usuario.
        - 'solicitud_rechazada': El correo no tiene cuenta porque su solicitud
              fue rechazada (queda el rastro en audit_logs).
        - 'datos_incorrectos': Contraseña errónea de un correo registrado.
        """
        usuario = LoginRepository.obtener_usuario_por_email(email)

        # Sin cuenta: se distingue un rechazo previo de un correo que nunca
        # se registró, para guiar al usuario con el mensaje correcto.
        if usuario is None:
            if LoginRepository.obtener_rechazo_por_email(email) is not None:
                return None, "solicitud_rechazada"
            return None, "correo_no_registrado"

        # Verificar contraseña
        if check_password_hash(usuario.password_hash, password):
            
            # 1. ¿Está desactivado manualmente?
            #    (En un invitado, is_active=False significa "pendiente de
            #    aprobación", no una cuenta bloqueada por el administrador).
            if not usuario.is_active and not usuario.is_guest:
                return usuario, "cuenta_desactivada"
            
            # 2. ¿Tiene sedes activas? (Solo si no es admin ni guest)
            if not usuario.is_admin and not usuario.is_guest:
                sedes_activas = [loc for loc in usuario.locations if loc.is_active]
                if not sedes_activas:
                    return usuario, "sin_sedes"
            
            # 3. Acceso permitido
            return usuario, "ok"
            
        # Contraseña incorrecta de un correo registrado: mensaje genérico,
        # sin revelar rol, estado ni sedes del usuario.
        return None, "datos_incorrectos"