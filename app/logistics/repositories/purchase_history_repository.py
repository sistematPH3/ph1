# app/logistics/repositories/purchase_history_repository.py
from app.models import Purchase, PurchaseDetail, Supplier

class PurchaseHistoryRepository:
    def __init__(self, db_connection):
        """
        Recibe la instancia de la base de datos (db) para mantener 
        la consistencia arquitectónica y la inyección de dependencias.
        """
        self.db = db_connection

    def get_filtered_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        """Saca el historial filtrado trayendo explícitamente el objeto compra y el nombre del proveedor"""
        # Solicitamos el objeto Purchase completo Y el campo name de la tabla Supplier
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
        """Busca una compra por su ID usando la sesión actual"""
        return self.db.session.query(Purchase).get(purchase_id)

    def get_details_by_purchase_id(self, purchase_id):
        """Obtiene los renglones/detalles de una compra específica incluyendo el SKU del producto"""
        from app.models import Product
        return self.db.session.query(PurchaseDetail, Product.sku.label('product_sku'))\
            .join(Product, PurchaseDetail.product_id == Product.id)\
            .filter(PurchaseDetail.purchase_id == purchase_id).all()
            
    def logical_annulment(self, purchase_id):
        """Ejecuta la anulación lógica cambiando el estado a ANULADO"""
        purchase = self.get_purchase_by_id(purchase_id)
        if purchase:
            purchase.status = 'ANNULLED'
            self.db.session.commit()
            return True
        return False