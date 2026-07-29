from datetime import datetime, timedelta

class PurchaseManagementService:
    def __init__(self, repository):
        self.repository = repository

    def get_formatted_history(self, current_user, start_date=None, end_date=None, supplier_id=None, status=None):
        raw_purchases = self.repository.get_filtered_history(
            start_date=start_date,
            end_date=end_date,
            supplier_id=supplier_id,
            status=status
        )
        
        formatted_history = []
        now = datetime.utcnow()
        local_now = now - timedelta(hours=4)
        
        for purchase, supplier_name in raw_purchases:
            if purchase.purchase_date:
                purchase_date_local = purchase.purchase_date - timedelta(hours=4)
            else:
                purchase_date_local = None
            
            can_modify = False
            if purchase.purchase_date and purchase.status == 'COMPLETED':
                if current_user.role_id == 1:
                    if purchase_date_local and purchase_date_local.month == local_now.month and purchase_date_local.year == local_now.year:
                        can_modify = True
                else:
                    if now - purchase.purchase_date <= timedelta(hours=24):
                        can_modify = True
            
            formatted_history.append({
                'id': purchase.id,
                'supplier_id': purchase.supplier_id,
                'supplier_name': supplier_name if supplier_name else "Proveedor N/A",
                'purchase_date': purchase_date_local, 
                'total_amount': purchase.total_amount,
                'currency': purchase.currency,
                'exchange_rate': purchase.exchange_rate,
                'invoice_url': purchase.invoice_url,
                'status': purchase.status,
                'can_modify': can_modify
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

    def process_annulment(self, purchase_id, current_user):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            raise ValueError("La compra no existe.")
            
        now = datetime.utcnow()
        local_now = now - timedelta(hours=4)
        purchase_date_local = purchase.purchase_date - timedelta(hours=4) if purchase.purchase_date else None
        
        if current_user.role_id == 1:
            if not purchase_date_local or purchase_date_local.month != local_now.month or purchase_date_local.year != local_now.year:
                raise ValueError("Acceso Denegado: Los Administradores solo pueden anular facturas registradas en el mes en curso.")
        else:
            if not purchase.purchase_date or now - purchase.purchase_date > timedelta(hours=24):
                raise ValueError("Acceso Denegado: El límite de 24 horas para anular esta factura ha expirado.")

        return self.repository.logical_annulment(purchase_id, current_user.id)

    def process_edit(self, purchase_id, current_user, new_items, reason):
        purchase = self.repository.get_purchase_by_id(purchase_id)
        if not purchase:
            raise ValueError("La compra no existe.")
            
        now = datetime.utcnow()
        local_now = now - timedelta(hours=4)
        purchase_date_local = purchase.purchase_date - timedelta(hours=4) if purchase.purchase_date else None
        
        if current_user.role_id == 1:
            if not purchase_date_local or purchase_date_local.month != local_now.month or purchase_date_local.year != local_now.year:
                raise ValueError("Acceso Denegado: Los Administradores solo pueden editar facturas registradas en el mes en curso.")
        else:
            if not purchase.purchase_date or now - purchase.purchase_date > timedelta(hours=24):
                raise ValueError("Acceso Denegado: El límite de 24 horas para editar esta factura ha expirado.")

        return self.repository.logical_edit(purchase_id, current_user.id, new_items, reason)