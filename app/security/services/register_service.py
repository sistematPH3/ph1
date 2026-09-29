from ..repositories.register_repository import RegisterRepository
from ..requests.register_validators import validar_datos_registro
from app.models.security_model import User
from werkzeug.security import generate_password_hash


class RegisterService:
    @staticmethod
    def registrar_usuario(name, email, password):
        """
        Registra un usuario nuevo.

        El alta queda en estado 'pendiente': role_id 0 (invitado) e is_active
        False, que es lo que espera UserManagementRepository.get_pending_users
        para mostrarlo en la pantalla de aprobacion del administrador.

        Antes se creaba con is_active=True, y como LoginService solo rechaza
        usuarios con is_active False (y la comprobacion de sedes se omite para
        invitados), la persona se podia conectar sin pasar por la aprobacion.
        """
        es_valido, mensaje_error = validar_datos_registro(name, email, password)
        if not es_valido:
            return {"success": False, "message": mensaje_error}

        nuevo_usuario = User(
            name=name.strip(),
            email=email.strip(),
            password_hash=generate_password_hash(password),
            role_id=0,
            is_active=False,
        )

        if RegisterRepository.guardar_usuario(nuevo_usuario):
            return {
                "success": True,
                "message": "Usuario registrado. Un administrador debe aprobar tu cuenta antes de que puedas entrar.",
            }

        return {"success": False, "message": "Error interno al guardar en base de datos."}
