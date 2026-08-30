from decimal import Decimal, InvalidOperation
from datetime import datetime

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
    'INCIDENCIA_TEMPERATURA',
    'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE',
    'VIOLACION_CUSTODIA',
    'RECHAZO_POR_ESPACIO'
}

def _is_valid_date(value):
    """True si value es una fecha válida en formato 'YYYY-MM-DD' (o está vacío)."""
    if value is None or not str(value).strip():
        return True
    try:
        datetime.strptime(str(value).strip(), '%Y-%m-%d')
        return True
    except ValueError:
        return False

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
        
    notes_raw = payload.get("notes")
    notes = str(notes_raw).strip() if notes_raw is not None else ""
    raw_erroneous = payload.get("erroneous_products", [])
    
    has_discrepancy = False
    row_issue_count = 0
    seen_detail_ids = set()
    processed_items = []

    for item in items:
        if not isinstance(item, dict):
            errors.append("Cada renglón de la guía debe ser un objeto con sus campos.")
            continue

        detail_id = item.get("detail_id")
        if not isinstance(detail_id, int) or detail_id not in movement_details_map:
            errors.append("Uno de los insumos no pertenece a esta orden de traslado.")
            continue

        # Protección anti doble-asiento: si el mismo renglón de la guía se envía dos
        # veces, cada repetición acreditaría stock en destino (doble asiento). Debe
        # enviarse una sola fila por detalle; las cantidades se resumen en una sola.
        if detail_id in seen_detail_ids:
            errors.append("No puede enviar el mismo renglón de la guía más de una vez en la recepción.")
            continue
        seen_detail_ids.add(detail_id)
        
        detail = movement_details_map[detail_id]
        prod_name = getattr(detail, 'product_name', 'el insumo')

        if "received_quantity" not in item or item.get("received_quantity") in (None, ""):
            errors.append(f"Debe indicar la cantidad recibida para '{prod_name}'.")
            continue

        raw_received = item.get("received_quantity")
        item_condition = item.get("item_condition", "CONFORME")
        observed_lot = item.get("observed_physical_lot")
        
        if item_condition not in VALID_ITEM_CONDITIONS:
            errors.append(f"La condición del insumo '{prod_name}' no es válida.")
            continue

        try:
            received_qty = Decimal(str(raw_received))
        except (InvalidOperation, TypeError):
            errors.append(f"Cantidad recibida inválida para '{prod_name}'.")
            continue
            
        if received_qty < Decimal("0.00"):
            errors.append(f"La cantidad no puede ser negativa para '{prod_name}'.")
            continue
            
        item_has_issue = False
        if received_qty < detail.quantity:
            missing_qty = detail.quantity - received_qty
            has_discrepancy = True
            item_has_issue = True
        else:
            missing_qty = Decimal("0.00")
            if received_qty > detail.quantity:
                has_discrepancy = True
                item_has_issue = True

        if item_condition != "CONFORME":
            has_discrepancy = True
            item_has_issue = True

        if item_has_issue:
            row_issue_count += 1

        if item_condition == "LOTE_NO_COINCIDE":
            if not observed_lot or len(str(observed_lot).strip()) == 0:
                errors.append(f"Debe ingresar el lote impreso en el empaque para '{prod_name}'.")

        observed_exp_raw = item.get("observed_physical_expiration")
        if observed_exp_raw and not _is_valid_date(observed_exp_raw):
            errors.append(f"La fecha de vencimiento observada para '{prod_name}' no es válida (use AAAA-MM-DD).")
            continue

        processed_items.append({
            "detail_id": detail_id,
            "product_id": detail.product_id,
            "quantity": detail.quantity,
            "received_quantity": received_qty,
            "missing_quantity": missing_qty,
            "lot_number": detail.lot_number,
            "expiration_date": detail.expiration_date,
            "item_condition": item_condition,
            "observed_physical_lot": str(observed_lot).strip() if observed_lot else None,
            "observed_physical_expiration": item.get("observed_physical_expiration") or None
        })

    processed_erroneous = []
    if novelty_type == "PRODUCTO_ERRONEO":
        if not raw_erroneous:
            errors.append("Debe declarar al menos un insumo físico entregado por error.")

    # Productos que SÍ vienen en la orden digital. Un insumo que está en la guía no puede
    # declararse como "entregado por error": si va en la guía es porque fue solicitado, por lo
    # que solo puede estar completo, faltante o sobrante — nunca ser un producto no solicitado.
    manifested_product_ids = {
        detail.product_id for detail in movement_details_map.values()
    }

    declared_erroneous_products = []

    if raw_erroneous:
        if isinstance(raw_erroneous, dict):
            raw_erroneous = [raw_erroneous]
        elif not isinstance(raw_erroneous, list):
            errors.append("La lista de insumos no solicitados tiene un formato no válido.")
            raw_erroneous = []

        seen_erroneous = set()
        for idx, err_item in enumerate(raw_erroneous, start=1):
            if not isinstance(err_item, dict):
                errors.append(f"Insumo no solicitado #{idx}: Formato inválido.")
                continue

            err_prod_id = err_item.get("product_id")
            err_qty_raw = err_item.get("quantity")
            err_lot_raw = err_item.get("lot_number")

            if not err_prod_id or not str(err_prod_id).lstrip('-').isdigit() or int(err_prod_id) <= 0:
                errors.append(f"Insumo no solicitado #{idx}: Debe seleccionar un producto válido del catálogo.")
                continue

            prod_id = int(err_prod_id)

            # Normalizamos el lote/serial (sin espacios, minúsculas) para detectar duplicados reales.
            err_lot = str(err_lot_raw).strip().lower() if err_lot_raw else ""

            if prod_id in manifested_product_ids:
                errors.append(
                    f"Insumo no solicitado #{idx}: '{err_item.get('product_name') or prod_id}' ya viene en la guía "
                    "del traslado. Si llegó incompleto o de más, regístrelo como faltante/sobrante en el renglón; "
                    "un producto de la guía no puede declararse como entregado por error."
                )
                continue

            # Permite declarar el MISMO producto erróneo en varias filas cuando el lote/serial
            # difiere (p. ej. 100 kg del lote X + 50 kg del lote Y del mismo tomate). Solo se
            # bloquea cuando es el mismo producto CON el mismo lote: eso sí es una duplicación.
            err_key = (prod_id, err_lot)
            if err_key in seen_erroneous:
                errors.append(
                    f"Insumo no solicitado #{idx}: Ya declaró el producto '{err_item.get('product_name') or prod_id}' "
                    "con el mismo lote/serial. Si la devolución combina lotes distintos, use una fila por lote."
                )
                continue

            err_exp_raw = err_item.get("expiration_date")
            if err_exp_raw and not _is_valid_date(err_exp_raw):
                errors.append(
                    f"Insumo no solicitado #{idx}: Formato de fecha de vencimiento inválido (use AAAA-MM-DD)."
                )
                continue

            try:
                err_qty = Decimal(str(err_qty_raw))
                if err_qty <= Decimal("0.00"):
                    errors.append(f"Insumo no solicitado #{idx}: La cantidad física debe ser mayor a cero.")
                else:
                    seen_erroneous.add(err_key)
                    declared_erroneous_products.append({
                        "product_id": prod_id,
                        "quantity": float(err_qty),
                        "lot_number": (str(err_item.get("lot_number") or "").strip() or None),
                        "expiration_date": (err_item.get("expiration_date") or None)
                    })
                    has_discrepancy = True
            except (InvalidOperation, TypeError, ValueError):
                errors.append(f"Insumo no solicitado #{idx}: Formato de cantidad no numérico.")

    processed_erroneous = declared_erroneous_products

    # Resolución del tipo de novedad cuando hay insumos no solicitados (erróneos).
    # El operario puede declarar erróneos abajo Y además registrar incidencias en los
    # renglones de la guía. REGLA (decisión de diseño): INCIDENCIA_MIXTA solo cuando
    # hay DOS o más renglones con incidencia (faltante/sobrante/condición). Un único
    # renglón afectado + erróneos NO es mixta: queda PRODUCTO_ERRONEO y la diferencia
    # del renglón se registra aparte en la auditoría para que el arbitraje la resuelva.
    if declared_erroneous_products:
        if row_issue_count >= 2:
            novelty_type = "INCIDENCIA_MIXTA"
        else:
            novelty_type = "PRODUCTO_ERRONEO"

    # COHERENCIA TIPO-ESPECÍFICA (guard anti falso reporte): una clasificación
    # general específica debe tener un respaldo COHERENTE con su naturaleza, no solo
    # algún respaldo. Sin él, la orden quedaría en disputa con sus discrepancias
    # registradas por NADA (incluso un EXCESO era etiquetado como FALTANTE):
    #   - FALTANTE_CONTEO    : exige recibo < guía o un renglón marcado FALTANTE.
    #   - SOBRANTE_EXCEDENTE : exige recibo > guía o un renglón marcado SOBRANTE.
    #   - Calidad (TEMPERATURA/VIOLACION/LOTE/RECHAZO): exige la misma condición en
    #     al menos un renglón.
    #   - INCIDENCIA_MIXTA   : exige DOS o más renglones afectados (regla de diseño).
    # VENCIMIENTO_PROXIMO queda eximido (alerta FEFO general sin renglón requerido) y
    # CONFORME/PRODUCTO_ERRONEO se regulan en sus bloques propios.
    any_missing_row = any(
        Decimal(str(it["received_quantity"])) < Decimal(str(it["quantity"]))
        for it in processed_items
    )
    any_surplus_row = any(
        Decimal(str(it["received_quantity"])) > Decimal(str(it["quantity"]))
        for it in processed_items
    )
    row_conditions = {
        it.get("item_condition")
        for it in processed_items
        if it.get("item_condition") not in (None, "CONFORME")
    }

    novelty_requiring_backing = (
        'FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE', 'INCIDENCIA_TEMPERATURA',
        'LOTE_NO_COINCIDE', 'VIOLACION_CUSTODIA', 'RECHAZO_POR_ESPACIO',
        'INCIDENCIA_MIXTA'
    )

    if novelty_type in novelty_requiring_backing and not has_discrepancy:
        errors.append(
            "La clasificación general no coincide con los renglones: no hay ninguna "
            "condición ni diferencia de cantidad registrada que la respalde. "
            "Revise la tabla de insumos o cambie la clasificación a 'Recepción Conforme'."
        )
    elif novelty_type == 'FALTANTE_CONTEO' and not any_missing_row and 'FALTANTE_CONTEO' not in row_conditions:
        errors.append(
            "La clasificación general 'Faltante de Conteo' no coincide con los renglones: "
            "no hay ningún renglón con recibo inferior a la guía ni marcado como faltante. "
            "Revise la tabla de insumos o cambie la clasificación."
        )
    elif novelty_type == 'SOBRANTE_EXCEDENTE' and not any_surplus_row and 'SOBRANTE_EXCEDENTE' not in row_conditions:
        errors.append(
            "La clasificación general 'Sobrante / Excedente' no coincide con los renglones: "
            "no hay ningún renglón con recibo superior a la guía ni marcado como sobrante. "
            "Revise la tabla de insumos o cambie la clasificación."
        )
    elif novelty_type == 'INCIDENCIA_TEMPERATURA' and 'INCIDENCIA_TEMPERATURA' not in row_conditions:
        errors.append(
            "La clasificación general 'Ruptura de Cadena de Frío' no coincide con los renglones: "
            "ningún renglón está marcado con la condición correspondiente. Revise la tabla de insumos."
        )
    elif novelty_type == 'VIOLACION_CUSTODIA' and 'VIOLACION_CUSTODIA' not in row_conditions:
        errors.append(
            "La clasificación general 'Violación de Custodia' no coincide con los renglones: "
            "ningún renglón está marcado con la condición correspondiente. Revise la tabla de insumos."
        )
    elif novelty_type == 'LOTE_NO_COINCIDE' and 'LOTE_NO_COINCIDE' not in row_conditions:
        errors.append(
            "La clasificación general 'Lote no coincide con Guía' no coincide con los renglones: "
            "ningún renglón está marcado con la condición correspondiente. Revise la tabla de insumos."
        )
    elif novelty_type == 'RECHAZO_POR_ESPACIO' and 'RECHAZO_POR_ESPACIO' not in row_conditions:
        errors.append(
            "La clasificación general 'Rechazo Parcial por Espacio' no coincide con los renglones: "
            "ningún renglón está marcado con la condición correspondiente. Revise la tabla de insumos."
        )
    elif novelty_type == 'INCIDENCIA_MIXTA' and row_issue_count < 2:
        errors.append(
            "La clasificación general 'Incidencia Mixta' no coincide con los renglones: "
            "exige dos o más renglones afectados y solo hay uno. Revise la tabla de insumos "
            "o cambie la clasificación."
        )



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