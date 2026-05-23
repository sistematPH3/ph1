from app.security.repositories.audit_repository import AuditRepository
import logging

logger = logging.getLogger(__name__)

class AuditService:
    @staticmethod
    def registrar_evento(user_id, role_id, action, location_id=None):
        try:
            # El servicio le delega la escritura al repositorio
            AuditRepository.guardar_log(user_id, role_id, action, location_id)
            return True
        except Exception as e:
            logger.error(f"Error en capa de datos al auditar: {str(e)}")
            return False