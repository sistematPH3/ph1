# app/logistics/repositories/purchase_history_repository.py
from app.extensions import db  
from app.models import Purchase, PurchaseDetail, Supplier  # <-- Asegura el "app." antes de models

class PurchaseHistoryRepository:
    
    @staticmethod
    def get_filtered_history(start_date=None, end_date=None, supplier_id=None, status=None):
        query = db.session.query(Purchase).join(Supplier, Purchase.supplier_id == Supplier.id)
        
        if start_date:
            query = query.filter(Purchase.purchase_date >= start_date)
        if end_date:
            query = query.filter(Purchase.purchase_date <= end_date)
            
        if supplier_id:
            query = query.filter(Purchase.supplier_id == supplier_id)
            
        if status:
            query = query.filter(Purchase.status == status)
            
        return query.order_by(Purchase.purchase_date.desc()).all()

    @staticmethod
    def get_purchase_by_id(purchase_id):
        return Purchase.query.get(purchase_id)

    @staticmethod
    def get_details_by_purchase_id(purchase_id):
        return db.session.query(PurchaseDetail)\
            .filter(PurchaseDetail.purchase_id == purchase_id).all()
            
    @staticmethod
    def logical_annulment(purchase_id):
        purchase = Purchase.query.get(purchase_id)
        if purchase:
            purchase.status = 'ANNULLED'
            db.session.commit()
            return True
        return False