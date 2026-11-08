from decimal import Decimal, InvalidOperation

class PurchaseValidator:
    @staticmethod
    def validate_header(data):
        errors = {}
        
        if not data.get('supplier_id'):
            errors['supplier_id'] = "Debes seleccionar un proveedor válido."
        else:
            try:
                supplier_id = int(data['supplier_id'])
                if supplier_id <= 0:
                    errors['supplier_id'] = "Identificador de proveedor inválido."
            except (ValueError, TypeError):
                errors['supplier_id'] = "El proveedor debe ser un identificador numérico."

        currency = str(data.get('currency', '')).strip().upper()
        if not currency or currency not in ('USD', 'EUR'):
            errors['currency'] = "La moneda debe ser obligatoriamente USD o EUR."

        exchange_rate_raw = data.get('exchange_rate')
        if exchange_rate_raw is None or str(exchange_rate_raw).strip() == '':
            errors['exchange_rate'] = "La tasa de cambio es obligatoria."
        else:
            try:
                rate = Decimal(str(exchange_rate_raw))
                if rate <= Decimal('0.00'):
                    errors['exchange_rate'] = "La tasa de cambio debe ser un número mayor a cero."
                elif rate > Decimal('999999.99'):
                    errors['exchange_rate'] = "La tasa de cambio excede el límite permitido."
            except (InvalidOperation, TypeError, ValueError):
                errors['exchange_rate'] = "La tasa de cambio debe ser un valor numérico válido."

        if not data.get('user_id'):
            errors['user_id'] = "El usuario comprador es obligatorio."

        return errors

    @staticmethod
    def validate_items(items):
        errors = {}
        
        if not isinstance(items, list) or len(items) == 0:
            return {"items": "Debe incluir al menos un producto en la tabla de compras."}
            
        for index, item in enumerate(items):
            prod_id_raw = item.get('product_id')
            if not prod_id_raw:
                errors[f'item_{index}_product_id'] = "Debes seleccionar un producto válido."
            else:
                try:
                    if int(prod_id_raw) <= 0:
                        errors[f'item_{index}_product_id'] = "Identificador de producto inválido."
                except (ValueError, TypeError):
                    errors[f'item_{index}_product_id'] = "El producto debe ser un número entero."

            qty_raw = item.get('quantity')
            try:
                qty = Decimal(str(qty_raw))
                if qty <= Decimal('0.00'):
                    errors[f'item_{index}_quantity'] = "La cantidad debe ser mayor a 0."
                elif qty > Decimal('999999.99'):
                    errors[f'item_{index}_quantity'] = "La cantidad excede el límite permitido (máx 999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_quantity'] = "Cantidad numérica inválida."

            price_raw = item.get('foreign_price')
            try:
                price = Decimal(str(price_raw))
                if price <= Decimal('0.00'):
                    errors[f'item_{index}_foreign_price'] = "El precio debe ser mayor a 0."
                elif price > Decimal('999999.99'):
                    errors[f'item_{index}_foreign_price'] = "El precio excede el límite permitido (máx 999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_foreign_price'] = "Precio numérico inválido."
                
        return errors

    @classmethod
    def validate_create(cls, data):
        if not data or not isinstance(data, dict):
            return False, {"error": "No se proporcionaron datos para procesar la compra."}

        header_errors = cls.validate_header(data)
        item_errors = cls.validate_items(data.get('items', []))
        
        all_errors = {**header_errors, **item_errors}
        return len(all_errors) == 0, all_errors