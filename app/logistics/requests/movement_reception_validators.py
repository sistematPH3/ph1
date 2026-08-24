from decimal import Decimal, InvalidOperation

VALID_NOVELTY_TYPES = {
    'CONFORME',
    'FALTANTE_CONTEO',
    'SOBRANTE_EXCEDENTE',
    'PRODUCTO_ERRONEO',
    'VIOLACION_CUSTODIA',
    'INCIDENCIA_TEMPERATURA',
    'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE',
    'RECHAZO_POR_ESPACIO'
}

def validate_reception_payload(payload, movement_details_map):
    errors = []
    
    if not isinstance(payload, dict):
        return False, ["Payload inválido. Se esperaba un objeto JSON."]
    
    items = payload.get("items")
    if not items or not isinstance(items, list):
        return False, ["La lista de insumos a recibir no puede estar vacía."]
    
    novelty_type = payload.get("novelty_type", "CONFORME")
    if novelty_type not in VALID_NOVELTY_TYPES:
        errors.append(f"Tipo de novedad no válido: {novelty_type}")
        
    notes = payload.get("notes", "").strip()
    
    has_discrepancy = False
    processed_items = []

    for item in items:
        detail_id = item.get("detail_id")
        if detail_id not in movement_details_map:
            errors.append(f"El detalle ID {detail_id} no pertenece a este traslado.")
            continue
            
        detail = movement_details_map[detail_id]
        raw_received = item.get("received_quantity")
        
        try:
            received_qty = Decimal(str(raw_received))
        except (InvalidOperation, TypeError):
            errors.append(f"Cantidad recibida inválida para el insumo ID {detail.product_id}.")
            continue
            
        if received_qty < Decimal("0.00"):
            errors.append(f"La cantidad recibida no puede ser negativa para el insumo ID {detail.product_id}.")
            continue
            
        if received_qty < detail.quantity:
            missing_qty = detail.quantity - received_qty
            has_discrepancy = True
        else:
            missing_qty = Decimal("0.00")
            if received_qty > detail.quantity:
                has_discrepancy = True
            
        processed_items.append({
            "detail_id": detail_id,
            "product_id": detail.product_id,
            "quantity": detail.quantity,
            "received_quantity": received_qty,
            "missing_quantity": missing_qty,
            "lot_number": detail.lot_number,
            "expiration_date": detail.expiration_date
        })

    if (novelty_type != "CONFORME" or has_discrepancy) and len(notes) < 5:
        errors.append("Debe ingresar una justificación/nota de muelle de al menos 5 caracteres al reportar novedades.")

    if errors:
        return False, errors

    return True, {
        "novelty_type": novelty_type,
        "notes": notes,
        "items": processed_items,
        "has_discrepancy": has_discrepancy
    }