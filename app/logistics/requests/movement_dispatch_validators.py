from datetime import datetime

class MovementDispatchValidator:
    @staticmethod
    def validate_dispatch_payload(data):
        """
        Valida que el JSON recibido de la vista contenga todos los campos obligatorios
        y que los valores numéricos y fechas sean coherentes.
        """
        errors = []

        if not data:
            return False, ["No se recibieron datos en la solicitud."]

        origin_id = data.get('origin_location_id')
        destination_id = data.get('destination_location_id')
        items = data.get('items', [])

        # 1. Validar Sedes
        if not origin_id or not str(origin_id).isdigit():
            errors.append("Debe seleccionar una sede de origen válida.")
        
        if not destination_id or not str(destination_id).isdigit():
            errors.append("Debe seleccionar una sede de destino válida.")

        if origin_id and destination_id and int(origin_id) == int(destination_id):
            errors.append("La sede de origen y la sede de destino no pueden ser la misma.")

        # 2. Validar Lista de Ítems
        if not items or not isinstance(items, list) or len(items) == 0:
            errors.append("El despacho debe incluir al menos un producto en el detalle.")
        else:
            for index, item in enumerate(items, start=1):
                product_id = item.get('product_id')
                quantity = item.get('quantity')
                expiration_date = item.get('expiration_date')

                if not product_id or not str(product_id).isdigit():
                    errors.append(f"Línea {index}: Debe seleccionar un producto válido.")

                try:
                    qty = float(quantity)
                    if qty <= 0:
                        errors.append(f"Línea {index}: La cantidad debe ser mayor a cero.")
                except (ValueError, TypeError):
                    errors.append(f"Línea {index}: La cantidad especificada no es un número válido.")

                if expiration_date:
                    try:
                        datetime.strptime(expiration_date, '%Y-%m-%d')
                    except ValueError:
                        errors.append(f"Línea {index}: La fecha de vencimiento debe tener formato AAAA-MM-DD.")

        if errors:
            return False, errors

        return True, None