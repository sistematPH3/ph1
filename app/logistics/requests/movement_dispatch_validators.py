from datetime import datetime

class MovementDispatchValidator:

    @staticmethod
    def validate_dispatch_payload(data):
        errors = []

        if not data or not isinstance(data, dict):
            return False, ["No se recibieron datos válidos en la solicitud."]

        origin_id = data.get('origin_location_id')
        destination_id = data.get('destination_location_id')
        items = data.get('items', [])

        if not origin_id or not str(origin_id).isdigit() or int(origin_id) <= 0:
            errors.append("Debe seleccionar una sede de origen válida.")

        if not destination_id or not str(destination_id).isdigit() or int(destination_id) <= 0:
            errors.append("Debe seleccionar una sede de destino válida.")

        if origin_id and destination_id and int(origin_id) == int(destination_id):
            errors.append("La sede de origen y la sede de destino no pueden ser la misma.")

        if not items or not isinstance(items, list) or len(items) == 0:
            errors.append("El despacho debe incluir al menos un producto en el detalle.")
        elif len(items) > 25:
            errors.append("El despacho no puede exceder los 25 renglones por orden.")
        else:
            for index, item in enumerate(items, start=1):
                product_id = item.get('product_id')
                quantity = item.get('quantity')
                lot_number = item.get('lot_number')
                expiration_date = item.get('expiration_date')

                if not product_id or not str(product_id).isdigit() or int(product_id) <= 0:
                    errors.append(f"Línea {index}: Debe seleccionar un producto válido.")

                try:
                    qty = float(quantity)
                    if qty <= 0.001:
                        errors.append(f"Línea {index}: La cantidad debe ser mayor a cero.")
                    elif qty > 999999.99:
                        errors.append(f"Línea {index}: La cantidad excede el límite numérico permitido.")
                except (ValueError, TypeError):
                    errors.append(f"Línea {index}: La cantidad especificada no es un número válido.")

                if not lot_number or not isinstance(lot_number, str) or not lot_number.strip():
                    errors.append(f"Línea {index}: El número de lote es obligatorio.")

                if expiration_date:
                    try:
                        datetime.strptime(expiration_date, '%Y-%m-%d')
                    except ValueError:
                        errors.append(f"Línea {index}: La fecha de vencimiento debe tener formato AAAA-MM-DD.")

        if errors:
            return False, errors

        return True, None