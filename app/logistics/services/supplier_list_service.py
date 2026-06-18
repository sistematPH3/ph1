# app/logistics/services/supplier_list_service.py

class SupplierListService:
    def __init__(self, repository):
        """Inyección del repositorio específico de listado de proveedores"""
        self.repository = repository

    def get_formatted_suppliers(self, search_term=None, status_filter=None):
        """Obtiene la colección procesada y la formatea limpiamente para el HTML"""
        raw_data = self.repository.get_all_with_last_purchase(
            search_term=search_term, 
            status_filter=status_filter
        )
        
        formatted_list = []
        for supplier, last_purchase_date in raw_data:
            formatted_list.append({
                'id': supplier.id,
                'name': supplier.name,
                'tax_id': supplier.tax_id,
                'contact_name': supplier.contact_name or "Sin contacto asignado",
                'phone': supplier.phone or "N/A",
                'email': supplier.email or "N/A",
                'status': supplier.status or "ACTIVE",
                'last_purchase_date': last_purchase_date  # Retorna el datetime o None
            })
        return formatted_list

    def process_status_toggle(self, supplier_id):
        """Ejecuta la acción de negocio para cambiar el estado de un proveedor"""
        return self.repository.toggle_supplier_status(supplier_id)