from decimal import Decimal, InvalidOperation
from datetime import date, datetime

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

LOTE_MISMATCH_CONTRADICTION_MESSAGE = (
    "El lote físico ingresado coincide con el de la guía; "
    "no puedes reportar una discrepancia de lote."
)


def is_lot_mismatch_contradiction(message):
    """True si la respuesta de validación corresponde a la contradicción de lote.

    Permite que la ruta responda 400 a este rechazo puntual sin alterar el 422
    que usan las demás validaciones de recepción.
    """
    mensajes = message if isinstance(message, (list, tuple)) else [message]
    return any(
        LOTE_MISMATCH_CONTRADICTION_MESSAGE in str(m) for m in mensajes
    )


NEAR_EXPIRY_CONTRADICTION_MESSAGE = (
    "Este producto aún tiene amplia vida útil; "
    "no puedes reportar Alerta de Vencimiento Próximo."
)


def is_near_expiry_contradiction(message):
    """True si el rechazo corresponde a un 'Vencimiento Próximo' sin sustento.

    Cubre el mensaje de este validador (fecha explícita fuera del umbral) y el
    del servicio (fecha resuelta por lote, vencida o inexistente), para que la
    ruta responda 400 en todos los casos sin alterar el 422 de las demás reglas.
    """
    mensajes = message if isinstance(message, (list, tuple)) else [message]
    for m in mensajes:
        texto = str(m)
        if NEAR_EXPIRY_CONTRADICTION_MESSAGE in texto:
            return True
        if "se marcó como 'Vencimiento Próximo'" in texto:
            return True
    return False


def _parse_fecha(value):
    """Convierte a date un valor ISO 'YYYY-MM-DD', datetime o date; None si no se puede."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _normalizar_lote(value):
    """Clave de comparación de lotes: mayúsculas/minúsculas y espacios.

    Se colapsan los espacios internos además de recortar los extremos, para que
    "LOTE  12 " y "lote 12" se consideren el MISMO lote y no abran una disputa
    falsa por un detalle de tipeo.
    """
    return " ".join(str(value or "").split()).casefold()


def _is_valid_date(value):
    """True si value es una fecha válida en formato 'YYYY-MM-DD' (o está vacío)."""
    if value is None or not str(value).strip():
        return True
    try:
        datetime.strptime(str(value).strip(), '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_reception_payload(payload, movement_details_map,
                               umbral_vencimiento_dias=7, hoy=None,
                               resolved_expirations=None, is_return=False):
    """Valida el payload de recepción completo.

    resolved_expirations: {detail_id: date} con el vencimiento REAL heredado
    (retornos). En un retorno la fecha del lote es inmutable: se ignora lo que el
    cliente envíe como fecha observada y se evalúa solo la heredada.
    """
    errors = []
    resolved_expirations = resolved_expirations or {}
    
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

        # Vencimiento REAL del renglón: en un retorno lo aporta la resolución
        # heredada del despacho original (la fecha es inmutable desde el ingreso).
        detail_expiration = (
            resolved_expirations.get(detail_id)
            or getattr(detail, "expiration_date", None)
        )

        if "received_quantity" not in item or item.get("received_quantity") in (None, ""):
            errors.append(f"Debe indicar la cantidad recibida para '{prod_name}'.")
            continue

        raw_received = item.get("received_quantity")
        item_condition = item.get("item_condition", "CONFORME")
        observed_lot = item.get("observed_physical_lot")
        
        if item_condition not in VALID_ITEM_CONDITIONS:
            errors.append(f"La condición del insumo '{prod_name}' no es válida.")
            continue

        # CONTRADICCIÓN EN "LOTE NO COINCIDE": si el operario marcó esa
        # condición pero el lote físico observado ES el mismo que trae la guía
        # (comparación sin espacios repetidos ni distinción de mayúsculas), no
        # hay discrepancia real. Se rechaza la recepción para que el operador
        # corrija la condición; no se anula en silencio.
        if (
            item_condition == "LOTE_NO_COINCIDE"
            and observed_lot
            and str(observed_lot).strip()
            and detail.lot_number
            and _normalizar_lote(observed_lot) == _normalizar_lote(detail.lot_number)
        ):
            errors.append(
                f"{LOTE_MISMATCH_CONTRADICTION_MESSAGE} "
                f"Insumo: '{prod_name}'."
            )
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

        # Coherencia de la condición DE CANTIDAD a nivel de renglón (regla de Mariuska):
        # un SOBRANTE exige recibir MÁS de lo despachado, y un FALTANTE exige recibir
        # MENOS. Si la condición declarada contradice la cantidad (p. ej. "sobrante" con
        # la misma cantidad que llegó), se rechaza en vez de registrar un falso sobrante.
        row_has_surplus_qty = received_qty > detail.quantity
        row_has_missing_qty = received_qty < detail.quantity
        if item_condition == "SOBRANTE_EXCEDENTE" and not row_has_surplus_qty:
            errors.append(
                f"Indicó 'Sobrante / Excedente' para '{prod_name}', pero la cantidad recibida "
                "no es MAYOR a la despachada. Un sobrante exige recibir más de lo despachado."
            )
            continue
        if item_condition == "FALTANTE_CONTEO" and not row_has_missing_qty:
            errors.append(
                f"Indicó 'Faltante de Conteo' para '{prod_name}', pero la cantidad recibida "
                "no es MENOR a la despachada. Un faltante exige recibir menos de lo despachado."
            )
            continue
        # 'Rechazo por espacio' implica que una parte de la carga NO se descargó
        # (no cupo en la sede). Si la cantidad recibida es igual a la despachada
        # no hubo rechazo alguno y la condición es incoherente.
        if item_condition == "RECHAZO_POR_ESPACIO" and not row_has_missing_qty:
            errors.append(
                f"Indicó 'Rechazo por Espacio' para '{prod_name}', pero la cantidad recibida "
                "no es MENOR a la despachada. La cantidad que no cupo debe quedar como "
                "faltante de descarga para que retorne al almacén central."
            )
            continue

        if item_has_issue:
            row_issue_count += 1

        if item_condition == "LOTE_NO_COINCIDE":
            if not observed_lot or len(str(observed_lot).strip()) == 0:
                errors.append(f"Debe ingresar el lote impreso en el empaque para '{prod_name}'.")

        observed_exp_raw = item.get("observed_physical_expiration")
        if observed_exp_raw and not _is_valid_date(observed_exp_raw):
            errors.append(f"La fecha de vencimiento observada para '{prod_name}' no es válida (use AAAA-MM-DD).")
            continue

        # CONTRADICCIÓN DE "ALERTA DE VENCIMIENTO PRÓXIMO": la novedad solo se
        # sostiene si el lote vence dentro del umbral configurado. Con la fecha
        # explícita (vencimiento manual observado o el de la guía) se rechaza de
        # inmediato; el servicio repite la regla con la fecha resuelta por lote.
        if item_condition == "VENCIMIENTO_PROXIMO":
            observed_exp = _parse_fecha(observed_exp_raw)
            real_exp = _parse_fecha(detail_expiration)
            if is_return:
                # En un RETORNO la fecha se hereda del movimiento original: no se
                # puede alterar ni declarar la novedad sin fecha real.
                if observed_exp is not None and real_exp is not None and observed_exp != real_exp:
                    errors.append(
                        "La fecha de vencimiento de un retorno se hereda del movimiento "
                        f"original y no puede modificarse. Insumo: '{prod_name}'."
                    )
                    continue
                if real_exp is None:
                    errors.append(
                        f"El insumo '{prod_name}' se marcó como 'Vencimiento Próximo', pero su "
                        "lote no tiene una fecha de vencimiento real registrada en el retorno. "
                        "Cambie la condición o corrija el lote antes de continuar."
                    )
                    continue
                fecha_exp = real_exp
            else:
                fecha_exp = observed_exp or real_exp
            if fecha_exp is not None:
                dias_para_vencer = (fecha_exp - (hoy or date.today())).days
                if dias_para_vencer > int(umbral_vencimiento_dias):
                    errors.append(
                        f"{NEAR_EXPIRY_CONTRADICTION_MESSAGE} "
                        f"Insumo: '{prod_name}' (vence en {dias_para_vencer} días)."
                    )
                    continue

        # Validación estructural de los LOTES DEL SOBRANTE (multilote). La existencia
        # en BD y la coherencia de sumas se verifican en el servicio (que sí tiene
        # acceso al repositorio); aquí solo se valida el formato/estructura.
        raw_surplus_lots = item.get("surplus_lots") or []
        surplus_lots = []
        if isinstance(raw_surplus_lots, list):
            for i, sl in enumerate(raw_surplus_lots, start=1):
                if not isinstance(sl, dict):
                    errors.append(f"Lote de sobrante #{i} de '{prod_name}': Formato inválido.")
                    continue
                sl_lot = str(sl.get("lot") or "").strip()
                sl_exp = sl.get("expiration_date")
                if sl_exp and not _is_valid_date(sl_exp):
                    errors.append(
                        f"Lote de sobrante #{i} de '{prod_name}': "
                        "fecha de vencimiento inválida (use AAAA-MM-DD)."
                    )
                surplus_lots.append({
                    "lot": sl_lot or None,
                    "expiration_date": sl_exp or None,
                    "quantity": sl.get("quantity", 0)
                })

        processed_items.append({
            "detail_id": detail_id,
            "product_id": detail.product_id,
            "quantity": detail.quantity,
            "received_quantity": received_qty,
            "missing_quantity": missing_qty,
            "lot_number": detail.lot_number,
            "expiration_date": detail_expiration,
            "item_condition": item_condition,
            "observed_physical_lot": str(observed_lot).strip() if observed_lot else None,
            "observed_physical_expiration": item.get("observed_physical_expiration") or None,
            "surplus_lots": surplus_lots
        })

    # Integridad de la guía: la recepción debe declarar TODOS los renglones del
    # movimiento. Si falta alguno, su received_quantity quedaría NULL en la BD
    # (datos perdidos en silencio para auditorías/reportes/arbitraje). La UI
    # siempre envía todos los renglones; este guard protege el path por API/script.
    missing_detail_ids = set(movement_details_map.keys()) - set(seen_detail_ids)
    if missing_detail_ids:
        errors.append(
            "La recepción debe declarar todos los renglones de la guía. Faltan los "
            f"renglones #{', #'.join(map(str, sorted(missing_detail_ids)))}. "
            "Envíe la cantidad recibida para cada insumo del traslado."
        )

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
    #   - VENCIMIENTO_PROXIMO: exige la condición en al menos un renglón. El umbral
    #     se valida con la fecha REAL del lote, que es un dato por renglón: sin
    #     renglón marcado no hay fecha que evaluar y la novedad se aceptaría a
    #     ciegas (era el hueco que permitía "cualquier fecha").
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
        'INCIDENCIA_MIXTA', 'VENCIMIENTO_PROXIMO'
    )

    if novelty_type == 'VENCIMIENTO_PROXIMO' and 'VENCIMIENTO_PROXIMO' not in row_conditions:
        errors.append(
            "La clasificación general 'Vencimiento Próximo' exige marcar el renglón del lote "
            "afectado: el umbral se valida contra la fecha real del lote y sin renglón no hay "
            "fecha que evaluar. Marque el insumo o cambie la clasificación."
        )
    elif novelty_type in novelty_requiring_backing and not has_discrepancy:
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
    elif novelty_type == 'SOBRANTE_EXCEDENTE' and not any_surplus_row:
        errors.append(
            "La clasificación general 'Sobrante / Excedente' exige que la cantidad recibida "
            "sea MAYOR a la despachada: no hay ningún renglón con recibo superior a la guía. "
            "Un sobrante no puede declararse con la misma cantidad que se despachó. "
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