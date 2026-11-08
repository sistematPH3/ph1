from datetime import datetime, time, timedelta

from decimal import ROUND_HALF_UP, Decimal


class PurchaseManagementService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _local_to_utc_bounds(start_date, end_date):
        """Convierte fechas locales (America/Caracas, UTC-4) a rangos UTC.

        El sistema guarda purchase_date en UTC; la fecha mostrada es local.
        Un día local D corresponde en UTC al intervalo [D 04:00, D+1 04:00).
        """
        start_dt = None
        if start_date:
            start_dt = datetime.combine(start_date, time.min) + timedelta(hours=4)
        end_dt = None
        if end_date:
            end_dt = (datetime.combine(end_date, time.min) + timedelta(days=1)) + timedelta(hours=4)
        return start_dt, end_dt

    def get_formatted_history(self, current_user, start_date=None, end_date=None, supplier_id=None, status=None):
        start_dt, end_dt = self._local_to_utc_bounds(start_date, end_date)

        raw_purchases = self.repository.get_filtered_history(
            start_date=start_dt,
            end_date=end_dt,
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

            total_amount = purchase.total_amount if purchase.total_amount is not None else Decimal('0.00')
            exchange_rate = purchase.exchange_rate if purchase.exchange_rate is not None else Decimal('0.00')
            total_bs = (total_amount * exchange_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            formatted_history.append({
                'id': purchase.id,
                'supplier_id': purchase.supplier_id,
                'supplier_name': supplier_name if supplier_name else "Proveedor N/A",
                'purchase_date': purchase_date_local, 
                'total_amount': total_amount,
                'total_bs': total_bs,
                'currency': purchase.currency,
                'exchange_rate': exchange_rate,
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