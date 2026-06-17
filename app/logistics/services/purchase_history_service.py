# app/logistics/services/purchase_history_service.py
from app.logistics.repositories.purchase_history_repository import PurchaseHistoryRepository

class PurchaseHistoryService:
    
    @staticmethod
    def get_formatted_history(start_date=None, end_date=None, supplier_id=None, status=None):
        """
        Lógica de negocio para obtener y preparar el historial de compras.
        """
        # Forzamos la importación del archivo de rutas AQUÍ para que Flask 
        # "despierte" el Blueprint en cuanto se invoque el servicio.
        from app.logistics.routes import purchase_history_routes
        
        return PurchaseHistoryRepository.get_filtered_history(
            start_date=start_date,
            end_date=end_date,
            supplier_id=supplier_id,
            status=status
        )

    @staticmethod
    def get_purchase_details_summary(purchase_id):
        """
        Coordina la búsqueda de la cabecera y sus renglones detallados.
        """
        from app.logistics.routes import purchase_history_routes
        
        purchase = PurchaseHistoryRepository.get_purchase_by_id(purchase_id)
        if not purchase:
            return None

        details = PurchaseHistoryRepository.get_details_by_purchase_id(purchase_id)
        
        return {
            "purchase": purchase,
            "details": details
        }
            
    @staticmethod
    def process_annulment(purchase_id):
        """
        Ejecuta la regla de negocio para la anulación de una compra.
        """
        from app.logistics.routes import purchase_history_routes
        
        return PurchaseHistoryRepository.logical_annulment(purchase_id)