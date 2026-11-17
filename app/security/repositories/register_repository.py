import logging

from sqlalchemy import func

from app.models.security_model import User
from app import db  # Importamos la instancia de SQLAlchemy

logger = logging.getLogger(__name__)


class RegisterRepository:
    @staticmethod
    def existe_usuario_por_email(email):
        """Verifica si el correo ya está registrado (sin distinguir mayúsculas)."""
        email_normalizado = (email or '').strip().lower()
        if not email_normalizado:
            return False
        return (User.query
                .filter(func.lower(func.trim(User.email)) == email_normalizado)
                .first()) is not None

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