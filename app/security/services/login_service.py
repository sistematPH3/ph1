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
        - 'datos_incorrectos': Email o contraseña erróneos.
        """
        usuario = LoginRepository.obtener_usuario_por_email(email)
        
        # Verificar existencia y contraseña
        if usuario and check_password_hash(usuario.password_hash, password):
            
            # 1. ¿Está desactivado manualmente?
            if not usuario.is_active:
                return usuario, "cuenta_desactivada"
            
            # 2. ¿Tiene sedes activas? (Solo si no es admin ni guest)
            if not usuario.is_admin and not usuario.is_guest:
                sedes_activas = [loc for loc in usuario.locations if loc.is_active]
                if not sedes_activas:
                    return usuario, "sin_sedes"
            
            # 3. Acceso permitido
            return usuario, "ok"
            
        # Fallo por credenciales incorrectas
        return None, "datos_incorrectos"