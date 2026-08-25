from app.logistics.repositories.response_inbox_repository import ResponseInboxRepository

class ResponseInboxService:
    @staticmethod
    def get_responses_for_user(user):
        """
        Obtiene los traslados que ya contienen una respuesta del administrador.
        """
        return ResponseInboxRepository.get_admin_responses(user)