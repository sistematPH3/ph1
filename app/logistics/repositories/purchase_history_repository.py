from app.models import Purchase, PurchaseDetail, Supplier, Inventory, PurchaseAuditLog, Product
from decimal import Decimal

class PurchaseHistoryRepository:
    def __init__(self, db_connection):
        self.db = db_connection

    def get_filtered_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        query = self.db.session.query(Purchase, Supplier.name.label('supplier_name')).join(
            Supplier, Purchase.supplier_id == Supplier.id
        )
        
        if start_date:
            query = query.filter(Purchase.purchase_date >= start_date)
        if end_date:
            query = query.filter(Purchase.purchase_date <= end_date)
            
        if supplier_id:
            query = query.filter(Purchase.supplier_id == supplier_id)
            
        if status:
            query = query.filter(Purchase.status == status)
            
        return query.order_by(Purchase.purchase_date.desc()).all()

    def get_purchase_by_id(self, purchase_id):
        return self.db.session.query(Purchase).get(purchase_id)

    def get_details_by_purchase_id(self, purchase_id):
        from app.models import Product
        return self.db.session.query(PurchaseDetail, Product.sku.label('product_sku'))\
            .join(Product, PurchaseDetail.product_id == Product.id)\
            .filter(PurchaseDetail.purchase_id == purchase_id).all()
            
    def logical_annulment(self, purchase_id, user_id):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status == 'ANNULLED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(purchase_id=purchase_id).all()

            previous_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount) if purchase.total_amount else 0.0,
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate else 0.0,
                "status": purchase.status,
                "details": [
                    {
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price) if d.foreign_price else 0.0,
                        "price_bs": float(d.price_bs) if d.price_bs else 0.0
                    } for d in details
                ]
            }

            purchase.status = 'ANNULLED'

            for detail in details:
                product = self.db.session.query(Product).filter_by(id=detail.product_id).first()
                if product:
                    product.quantity -= detail.quantity
                    if product.quantity < 0:
                        product.quantity = Decimal('0.00')

                inventory_item = self.db.session.query(Inventory).filter_by(product_id=detail.product_id).first()
                if inventory_item:
                    inventory_item.current_quantity -= detail.quantity
                    if inventory_item.current_quantity < 0:
                        inventory_item.current_quantity = Decimal('0.00')

            audit_log = PurchaseAuditLog(
                purchase_id=purchase.id,
                action_type='ANNULLED',
                previous_data=previous_data,
                new_data=None,
                user_id=user_id
            )
            self.db.session.add(audit_log)

            self.db.session.commit()
            return True
        except Exception as e:
            self.db.session.rollback()
            raise e

    def logical_edit(self, purchase_id, user_id, new_items):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status == 'ANNULLED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(purchase_id=purchase_id).all()

            previous_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount) if purchase.total_amount else 0.0,
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate else 0.0,
                "status": purchase.status,
                "details": [
                    {
                        "id": d.id,
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price) if d.foreign_price else 0.0,
                        "price_bs": float(d.price_bs) if d.price_bs else 0.0
                    } for d in details
                ]
            }

            new_total_amount = Decimal('0.00')

            for detail in details:
                matching_new = next((item for item in new_items if int(item['id']) == detail.id), None)
                
                if matching_new:
                    new_qty = Decimal(str(matching_new['quantity']))
                    new_price = Decimal(str(matching_new['foreign_price']))
                    
                    qty_diff = new_qty - detail.quantity
                    
                    if qty_diff != Decimal('0.00'):
                        product = self.db.session.query(Product).filter_by(id=detail.product_id).first()
                        if product:
                            product.quantity += qty_diff
                            if product.quantity < 0:
                                product.quantity = Decimal('0.00')
                                
                        inventory_item = self.db.session.query(Inventory).filter_by(product_id=detail.product_id).first()
                        if inventory_item:
                            inventory_item.current_quantity += qty_diff
                            if inventory_item.current_quantity < 0:
                                inventory_item.current_quantity = Decimal('0.00')
                    
                    detail.quantity = new_qty
                    detail.foreign_price = new_price
                    detail.price_bs = new_price * purchase.exchange_rate
                    
                    new_total_amount += (new_qty * new_price)
                else:
                    new_total_amount += (detail.quantity * detail.foreign_price)

            purchase.total_amount = new_total_amount

            new_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount),
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate),
                "status": purchase.status,
                "details": [
                    {
                        "id": d.id,
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price),
                        "price_bs": float(d.price_bs)
                    } for d in details
                ]
            }

            audit_log = PurchaseAuditLog(
                purchase_id=purchase.id,
                action_type='EDIT',
                previous_data=previous_data,
                new_data=new_data,
                user_id=user_id
            )
            self.db.session.add(audit_log)

            self.db.session.commit()
            return True
        except Exception as e:
            self.db.session.rollback()
            raise e