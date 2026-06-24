import pytz

class PurchaseHistoryService:
    def __init__(self, repository):
        self.repository = repository

    def get_formatted_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        raw_purchases = self.repository.get_filtered_history(
            start_date=start_date,
            end_date=end_date,
            supplier_id=supplier_id,
            status=status
        )
        
        formatted_history = []
        
        utc_tz = pytz.utc
        caracas_tz = pytz.timezone('America/Caracas')
        for purchase, supplier_name in raw_purchases:
            if purchase.purchase_date:
                purchase_date_utc = utc_tz.localize(purchase.purchase_date)
                purchase_date_local = purchase_date_utc.astimezone(caracas_tz)
            else:
                purchase_date_local = None
            
            formatted_history.append({
                'id': purchase.id,
                'supplier_id': purchase.supplier_id,
                'supplier_name': supplier_name if supplier_name else "Proveedor N/A",
                'purchase_date': purchase_date_local, 
                'total_amount': purchase.total_amount,
                'currency': purchase.currency,
                'exchange_rate': purchase.exchange_rate,
                'invoice_url': purchase.invoice_url,
                'status': purchase.status
            })
            
        return formatted_history

    def get_purchase_details_summary(self, purchase_id):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            return None
            
        details = self.repository.get_details_by_purchase_id(purchase_id)
        return {
            "purchase": purchase,
            "details": details
        }

    def process_annulment(self, purchase_id, user_id):
        return self.repository.logical_annulment(purchase_id, user_id)

    def process_edit(self, purchase_id, user_id, new_items):
        return self.repository.logical_edit(purchase_id, user_id, new_items)