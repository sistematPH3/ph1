from sqlalchemy import func

from app.models.security_model import User
from app.models.waste_model import AuditLog


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

    @staticmethod
    def obtener_rechazo_por_email(email):
        """Devuelve el rechazo de solicitud más reciente de ese correo, si lo hay.

        El rechazo vive en `audit_logs` (tabla ya existente): no se conserva
        al usuario, así que el correo queda libre para volver a registrarse.
        Solo se consulta cuando el correo no tiene cuenta, de modo que un
        registro nuevo (pendiente o aprobado) siempre manda sobre el rechazo
        anterior.
        """
        email_normalizado = (email or '').strip().lower()
        if not email_normalizado:
            return None
        return (AuditLog.query
                .filter(
                    AuditLog.affected_table == 'users',
                    AuditLog.action == 'RECHAZO_SOLICITUD',
                    func.lower(func.trim(
                        AuditLog.changed_data['email'].astext
                    )) == email_normalizado,
                )
                .order_by(AuditLog.id.desc())
                .first())