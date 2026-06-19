from sqlalchemy import func
from app.models import Supplier, Purchase

class SupplierListRepository:
    def __init__(self, db_connection):
        """
        Recibe la instancia de la base de datos (db) para mantener 
        la consistencia arquitectónica y la inyección de dependencias.
        """
        self.db = db_connection

    def get_all_with_last_purchase(self, search_term=None, status_filter=None):
        """
        Trae los proveedores ordenados alfabéticamente junto con la fecha 
        de su última compra registrada. Permite filtrar por nombre/RIF y estatus.
        """
        query = self.db.session.query(
            Supplier,
            func.max(Purchase.purchase_date).label('last_purchase_date')
        ).outerjoin(Purchase, Supplier.id == Purchase.supplier_id)

        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                (Supplier.name.ilike(search_pattern)) | 
                (Supplier.tax_id.ilike(search_pattern))
            )

        if status_filter:
            query = query.filter(Supplier.status == status_filter)

        return query.group_by(Supplier.id).order_by(Supplier.name.asc()).all()

    def get_supplier_by_id(self, supplier_id):
        """Busca un proveedor específico por su ID único"""
        return self.db.session.query(Supplier).get(supplier_id)

    def get_by_id(self, supplier_id):
        """Alias de compatibilidad para evitar el AttributeError en las rutas"""
        return self.get_supplier_by_id(supplier_id)

    def toggle_supplier_status(self, supplier_id):
        """Cambia el estado lógico del proveedor entre ACTIVE e INACTIVE"""
        supplier = self.get_supplier_by_id(supplier_id)
        if supplier:
            current_status = supplier.status.strip().upper() if supplier.status else "ACTIVE"
            supplier.status = "INACTIVE" if current_status == "ACTIVE" else "ACTIVE"
            self.db.session.commit()
            return supplier.status
        return None