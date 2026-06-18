# app/logistics/services/purchase_history_service.py

class PurchaseHistoryService:
    def __init__(self, repository):
        """Inyección del repositorio de historial de compras"""
        self.repository = repository

    def get_formatted_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        """Obtiene el historial desde el repositorio y lo formatea limpiamente para la vista HTML"""
       
        raw_purchases = self.repository.get_filtered_history(
            start_date=start_date,
            end_date=end_date,
            supplier_id=supplier_id,
            status=status
        )
        
        formatted_history = []
        
       
        for purchase, supplier_name in raw_purchases:
            
            formatted_history.append({
                'id': purchase.id,
                'supplier_id': purchase.supplier_id,
                'supplier_name': supplier_name if supplier_name else "Proveedor N/A",
                'purchase_date': purchase.purchase_date,  # <-- Dejamos la fecha tal cual como venía originalmente
                'total_amount': purchase.total_amount,
                'currency': purchase.currency,
                'exchange_rate': purchase.exchange_rate,
                'invoice_url': purchase.invoice_url,
                'status': purchase.status
            })
            
        return formatted_history

    def get_purchase_details_summary(self, purchase_id):
        """Obtiene la cabecera y el desglose de productos de una compra específica"""
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            return None
            
        details = self.repository.get_details_by_purchase_id(purchase_id)
        return {
            "purchase": purchase,
            "details": details
        }

    def process_annulment(self, purchase_id):
        """Lógica de negocio para procesar la anulación de una compra"""
        return self.repository.logical_annulment(purchase_id)