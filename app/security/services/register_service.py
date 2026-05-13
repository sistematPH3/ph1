from ..repositories.register_repository import RegisterRepository
from ..requests.auth_validators import validar_credenciales_login
from ..requests.register_validators import validar_datos_registro
from app.models.security_model import User
from werkzeug.security import generate_password_hash

class RegisterService:
    @staticmethod
    def registrar_usuario(name, email, password):
        
        import re
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return {"success": False, "message": "Por favor, verifique el formato del correo."}

        if not password:
            return {"success": False, "message": "Por favor, ingrese la contraseña."}
        
        if len(password) < 6:
            return {"success": False, "message": "La contraseña debe tener mínimo 6 caracteres."}
            
        if len(password) > 12:
            return {"success": False, "message": "La contraseña debe tener máximo 12 caracteres."}

        chequeo_custom = validar_datos_registro(name, email)
        if not chequeo_custom["valido"]:
            return {"success": False, "message": "Este usuario ya existe."}
        
        hashed_password = generate_password_hash(password)
        nuevo_usuario = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            is_active=True 
        )

        resultado = RegisterRepository.guardar_usuario(nuevo_usuario)
        
        if resultado:
            return {"success": True, "message": "Usuario registrado con éxito."}
        else:
            return {"success": False, "message": "Error interno al guardar en base de datos."}