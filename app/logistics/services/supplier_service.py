class SupplierService:
    def __init__(self, supplier_repository):
        self.repository = supplier_repository

    def register_new_supplier(self, supplier_request):
        supplier_request.validate()
        
        if self.repository.find_by_tax_id(supplier_request.tax_id):
            raise ValueError(f"El proveedor con RIF {supplier_request.tax_id} ya se encuentra registrado en el sistema.")
        
        return self.repository.save(supplier_request)