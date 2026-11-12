import logging

from app.models.security_model import User
from app import db  # Importamos la instancia de SQLAlchemy

logger = logging.getLogger(__name__)


class RegisterRepository:
    @staticmethod
    def existe_usuario_por_email(email):
        """Verifica si el correo ya está registrado."""
        return User.query.filter_by(email=email).first() is not None

    @staticmethod
    def guardar_usuario(nuevo_usuario):
        """Guarda un objeto de usuario en la base de datos."""
        try:
            db.session.add(nuevo_usuario)
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            logger.exception("Error al registrar el usuario en la base de datos")
            return False