class PurchaseValidator:
    @staticmethod
    def validate_header(data):
        """Valida de forma estricta los campos de la cabecera de la factura."""
        errors = {}
        
        # Validar campos requeridos y no vacíos
        required_fields = {
            'supplier_id': "Debes seleccionar un proveedor válido.",
            'currency': "Debes especificar la moneda de la transacción.",
            'exchange_rate': "La tasa de cambio es obligatoria.",
            'user_id': "El usuario comprador es obligatorio."
        }
        
        for field, message in required_fields.items():
            if field not in data or data[field] is None or data[field] == '':
                errors[field] = message

        # Regla de negocio: Tasa de cambio no puede ser 0 ni negativa
        if 'exchange_rate' in data and data['exchange_rate'] is not None:
            try:
                rate = float(data['exchange_rate'])
                if rate <= 0:
                    errors['exchange_rate'] = "La tasa de cambio debe ser un número mayor a cero."
            except (ValueError, TypeError):
                errors['exchange_rate'] = "La tasa de cambio debe ser un valor numérico válido."
                
        return errors

    @staticmethod
    def validate_items(items):
        """Valida detalladamente el arreglo de productos e insumos agregados."""
        errors = {}
        
        if not isinstance(items, list) or len(items) == 0:
            return {"items": "Debe incluir al menos un producto en la tabla de compras."}
            
        for index, item in enumerate(items):
            # Validar existencia de claves
            if not item.get('product_id'):
                errors[f'item_{index}_product_id'] = "Debes seleccionar un producto."
                
            # Validar cantidades lógicas
            qty = item.get('quantity', 0)
            try:
                if float(qty) <= 0:
                    errors[f'item_{index}_quantity'] = "La cantidad debe ser mayor a 0."
            except (ValueError, TypeError):
                errors[f'item_{index}_quantity'] = "Cantidad inválida."
                
            # Validar precios lógicas
            price = item.get('foreign_price', 0)
            try:
                if float(price) <= 0:
                    errors[f'item_{index}_foreign_price'] = "El precio debe ser mayor a 0."
            except (ValueError, TypeError):
                errors[f'item_{index}_foreign_price'] = "Precio inválido."
                
        return errors