from ..repositories.login_repository import LoginRepository
from werkzeug.security import check_password_hash

class LoginService:
    @staticmethod
    def autenticar(email, password):
        usuario = LoginRepository.obtener_usuario_por_email(email)
        
       
        if usuario and usuario.is_active and check_password_hash(usuario.password_hash, password):
            return usuario
            
        return None