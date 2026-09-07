from decimal import Decimal, InvalidOperation

def validate_reversal_payload(data):
    if not data or not isinstance(data, dict):
        return {"is_valid": False, "errors": {"reason": "El cuerpo de la solicitud no es válido."}}

    reason = str(data.get("reason") or data.get("reversal_reason") or "").strip()
    if len(reason) < 15:
        return {
            "is_valid": False,
            "errors": {
                "reason": f"El motivo de reversión debe tener al menos 15 caracteres (actual: {len(reason)})."
            }
        }

    return {"is_valid": True, "reason": reason}

def validate_edit_payload(data):
    if not data or not isinstance(data, dict):
        return {"is_valid": False, "errors": {"general": "El cuerpo de la solicitud no es válido."}}

    errors = {}
    waste_type_id = data.get("waste_type_id")
    if not waste_type_id:
        errors["waste_type_id"] = "Debe seleccionar un tipo de merma."
    else:
        try:
            waste_type_id = int(waste_type_id)
        except (ValueError, TypeError):
            errors["waste_type_id"] = "Tipo de merma no válido."

    notes = str(data.get("notes") or "").strip()
    evidence_url = data.get("evidence_url")
    if evidence_url is not None:
        evidence_url = str(evidence_url).strip() or None

    lines_raw = data.get("lines") or data.get("details") or []
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        errors["lines"] = "La merma debe tener al menos una línea de producto."

    cleaned_lines = []
    for idx, item in enumerate(lines_raw):
        if not isinstance(item, dict):
            errors[f"line_{idx}"] = "Línea con formato incorrecto."
            continue

        product_id = item.get("product_id")
        lot_number = str(item.get("lot_number") or "").strip()
        raw_qty = item.get("quantity")
        raw_unit_cost = item.get("unit_cost", 0)
        exp_date = item.get("expiration_date") or None
        line_type_id = item.get("waste_type_id")

        if line_type_id not in (None, ""):
            try:
                line_type_id = int(line_type_id)
                if line_type_id <= 0:
                    errors[f"line_{idx}_waste_type_id"] = "Tipo de merma de la línea no válido."
                    line_type_id = None
            except (ValueError, TypeError):
                errors[f"line_{idx}_waste_type_id"] = "Tipo de merma de la línea no válido."
                line_type_id = None

        if not product_id:
            errors[f"line_{idx}_product"] = "Producto no especificado."
        if not lot_number:
            errors[f"line_{idx}_lot"] = "Número de lote requerido."

        try:
            qty = Decimal(str(raw_qty))
            if qty <= 0:
                errors[f"line_{idx}_qty"] = "La cantidad debe ser mayor a 0."
        except (InvalidOperation, TypeError):
            errors[f"line_{idx}_qty"] = "Cantidad numérica inválida."
            qty = Decimal("0.00")

        try:
            unit_cost = Decimal(str(raw_unit_cost))
            if unit_cost < 0:
                unit_cost = Decimal("0.0000")
        except (InvalidOperation, TypeError):
            unit_cost = Decimal("0.0000")

        subtotal_cost = (qty * unit_cost).quantize(Decimal("0.01"))

        evidence_urls_raw = item.get("evidence_urls") or item.get("photos") or []
        evidence_urls = []
        seen = set()
        if not isinstance(evidence_urls_raw, list):
            errors[f"line_{idx}_evidence_urls"] = "Las fotos de la línea deben venir como una lista."
            evidence_urls_raw = []
        for u in evidence_urls_raw:
            if isinstance(u, str) and u.strip() and u.strip() not in seen:
                seen.add(u.strip())
                evidence_urls.append(u.strip())
        if len(evidence_urls) > 10:
            errors[f"line_{idx}_evidence_urls"] = "Máximo 10 fotos por producto."
            evidence_urls = evidence_urls[:10]

        cleaned_lines.append({
            "product_id": int(product_id) if product_id else None,
            "lot_number": lot_number,
            "expiration_date": exp_date,
            "quantity": qty,
            "unit_cost": unit_cost,
            "subtotal_cost": subtotal_cost,
            "waste_type_id": line_type_id,
            "evidence_urls": evidence_urls
        })

    if errors:
        return {"is_valid": False, "errors": errors}

    return {
        "is_valid": True,
        "data": {
            "waste_type_id": waste_type_id,
            "notes": notes,
            "evidence_url": evidence_url,
            "lines": cleaned_lines
        }
    }