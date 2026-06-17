# app/logistics/requests/purchase_request.py
from app.logistics.requests.purchase_validators import PurchaseValidator

class PurchaseRequest:
    @staticmethod
    def validate_create(data):
        """Valida el JSON recibido para el registro de una compra usando el validador modular."""
        if not data:
            return False, {"error": "No se proporcionaron datos."}

        # Ejecutamos las validaciones modulares
        header_errors = PurchaseValidator.validate_header(data)
        item_errors = PurchaseValidator.validate_items(data.get('items', []))
        
        # Consolidamos todos los errores detectados en un solo diccionario
        all_errors = {**header_errors, **item_errors}

        return len(all_errors) == 0, all_errors