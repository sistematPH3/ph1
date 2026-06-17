class SupplierService:
    def __init__(self, supplier_repository):
        self.repository = supplier_repository

    def register_new_supplier(self, supplier_request):
        if not supplier_request.is_valid():
            raise ValueError("Datos del proveedor inválidos o campos exceden el límite.")
        
        # Aquí puedes meter lógica de negocio (ej. verificar si el tax_id ya existe)
        
        return self.repository.save(supplier_request)