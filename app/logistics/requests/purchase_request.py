# app/logistics/requests/purchase_request.py

class PurchaseRequest:
    @staticmethod
    def validate_create(data):
        """Valida el JSON recibido para el registro de una compra."""
        errors = {}

        if not data:
            return False, {"error": "No se proporcionaron datos."}

        # Validar campos obligatorios de la cabecera
        required_fields = ['supplier_id', 'currency', 'exchange_rate', 'user_id', 'items']
        for field in required_fields:
            if field not in data or data[field] is None:
                errors[field] = f"El campo '{field}' es obligatorio."

        # Validar que contenga artículos
        items = data.get('items', [])
        if not isinstance(items, list) or len(items) == 0:
            errors['items'] = "Debe incluir al menos un producto en la compra."
        else:
            # Validar cada artículo del detalle
            for index, item in enumerate(items):
                item_fields = ['product_id', 'quantity', 'foreign_price']
                for f in item_fields:
                    if f not in item or item[f] is None:
                        errors[f'item_{index}_{f}'] = f"El producto en la posición {index} requiere el campo '{f}'."
                
                # Validaciones de negocio lógicas
                if item.get('quantity', 0) <= 0:
                    errors[f'item_{index}_quantity'] = "La cantidad debe ser mayor a 0."
                if item.get('foreign_price', 0) <= 0:
                    errors[f'item_{index}_foreign'] = "El precio debe ser mayor a 0."

        # CORRECCIÓN CRÍTICA: Retornamos si es válido (True/False) junto al dict de errores
        return len(errors) == 0, errors