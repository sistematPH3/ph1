from decimal import Decimal, InvalidOperation

VALID_NOVELTY_TYPES = {
    'CONFORME',
    'FALTANTE_CONTEO',
    'SOBRANTE_EXCEDENTE',
    'PRODUCTO_ERRONEO',
    'INCIDENCIA_TEMPERATURA',
    'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE',
    'VIOLACION_CUSTODIA',
    'RECHAZO_POR_ESPACIO',
    'INCIDENCIA_MIXTA'
}

VALID_ITEM_CONDITIONS = {
    'CONFORME',
    'FALTANTE_CONTEO',
    'SOBRANTE_EXCEDENTE',
    'PRODUCTO_ERRONEO',
    'INCIDENCIA_TEMPERATURA',
    'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE',
    'VIOLACION_CUSTODIA',
    'RECHAZO_POR_ESPACIO'
}

def validate_reception_payload(payload, movement_details_map):
    errors = []
    
    if not isinstance(payload, dict):
        return False, ["Formato de solicitud no válido."]
    
    items = payload.get("items")
    if not items or not isinstance(items, list):
        return False, ["La lista de insumos a recibir no puede estar vacía."]
    
    novelty_type = payload.get("novelty_type", "CONFORME")
    if novelty_type not in VALID_NOVELTY_TYPES:
        errors.append("El tipo de novedad general seleccionado no es válido.")
        
    notes = payload.get("notes", "").strip()
    raw_erroneous = payload.get("erroneous_products", [])
    
    has_discrepancy = False
    processed_items = []

    for item in items:
        detail_id = item.get("detail_id")
        if detail_id not in movement_details_map:
            errors.append("Uno de los insumos no pertenece a esta orden de traslado.")
            continue
            
        detail = movement_details_map[detail_id]
        prod_name = getattr(detail, 'product_name', 'el insumo')
        raw_received = item.get("received_quantity")
        item_condition = item.get("item_condition", "CONFORME")
        observed_lot = item.get("observed_physical_lot")
        
        if item_condition not in VALID_ITEM_CONDITIONS:
            item_condition = "CONFORME"

        try:
            received_qty = Decimal(str(raw_received))
        except (InvalidOperation, TypeError):
            errors.append(f"Cantidad recibida inválida para '{prod_name}'.")
            continue
            
        if received_qty < Decimal("0.00"):
            errors.append(f"La cantidad no puede ser negativa para '{prod_name}'.")
            continue
            
        if received_qty < detail.quantity:
            missing_qty = detail.quantity - received_qty
            has_discrepancy = True
        else:
            missing_qty = Decimal("0.00")
            if received_qty > detail.quantity:
                has_discrepancy = True

        if item_condition != "CONFORME":
            has_discrepancy = True

        if item_condition == "LOTE_NO_COINCIDE":
            if not observed_lot or len(str(observed_lot).strip()) == 0:
                errors.append(f"Debe ingresar el lote impreso en el empaque para '{prod_name}'.")

        processed_items.append({
            "detail_id": detail_id,
            "product_id": detail.product_id,
            "quantity": detail.quantity,
            "received_quantity": received_qty,
            "missing_quantity": missing_qty,
            "lot_number": detail.lot_number,
            "expiration_date": detail.expiration_date,
            "item_condition": item_condition,
            "observed_physical_lot": str(observed_lot).strip() if observed_lot else None
        })

    processed_erroneous = []
    if raw_erroneous and (novelty_type == "PRODUCTO_ERRONEO" or novelty_type == "INCIDENCIA_MIXTA"):
        if isinstance(raw_erroneous, dict):
            raw_erroneous = [raw_erroneous]
            
        for idx, err_item in enumerate(raw_erroneous, start=1):
            err_prod_id = err_item.get("product_id")
            err_qty_raw = err_item.get("quantity")
            
            if not err_prod_id:
                errors.append(f"Insumo erróneo #{idx}: Debe seleccionar un producto del catálogo.")
                continue
                
            try:
                err_qty = Decimal(str(err_qty_raw))
                if err_qty <= Decimal("0.00"):
                    errors.append(f"Insumo erróneo #{idx}: La cantidad física debe ser mayor a cero.")
                else:
                    processed_erroneous.append({
                        "product_id": int(err_prod_id),
                        "quantity": float(err_qty)
                    })
                    has_discrepancy = True
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"Insumo erróneo #{idx}: Formato de cantidad no numérico.")

    if has_discrepancy and len(notes) < 5:
        errors.append("Debe ingresar una justificación en las notas de muelle (mínimo 5 caracteres).")

    if errors:
        return False, errors

    return True, {
        "novelty_type": novelty_type,
        "notes": notes,
        "items": processed_items,
        "erroneous_products": processed_erroneous,
        "has_discrepancy": has_discrepancy
    }