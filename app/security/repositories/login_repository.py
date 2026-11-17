from sqlalchemy import func

from app.models.security_model import User


class LoginRepository:
    @staticmethod
    def obtener_usuario_por_email(email):
        """Busca al usuario por correo de forma tolerante.

        El registro y la edición de personal guardan el correo tal como se
        escribió, mientras el login lo normaliza a minúsculas. Comparar en
        crudo hacía fallar cuentas reales guardadas con mayúsculas o espacios;
        la búsqueda se hace ahora sin distinguir mayúsculas ni espacios.
        """
        email_normalizado = (email or '').strip().lower()
        if not email_normalizado:
            return None
        return (User.query
                .filter(func.lower(func.trim(User.email)) == email_normalizado)
                .first())