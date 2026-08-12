from app.security.repositories.audit_user_repository import AuditUserRepository
import logging

logger = logging.getLogger(__name__)

class AuditUserService:
    @staticmethod
    def get_audit_history(current_user=None):
        # Transfiere el usuario actual al repositorio para que aplique el filtro
        return AuditUserRepository.get_user_audits(current_user=current_user)

    @staticmethod
    def registrar_modificacion(responsible_user_id, target_user_id, role_id, action, changed_data=None):
        try:
            AuditUserRepository.guardar_auditoria(
                responsible_user_id, 
                target_user_id, 
                role_id, 
                action, 
                changed_data
            )
            return True
        except Exception as e:
            logger.error(f"Error en capa de datos al auditar usuario: {str(e)}")
            return False