import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from app import db
from app.models import Product
from app.logistics.repositories.movement_reception_repository import MovementReceptionRepository
from app.logistics.requests.movement_reception_validators import validate_reception_payload


def _derive_auto_novelty(processed_items):
    """Replica la auto-clasificación del formulario (movement_reception.js) para
    derivar el estatus REAL cuando el payload llega CONFORME pero los renglones
    reflejan condiciones o diferencias de cantidad (solo posible vía API/script:
    en la UI el JS ya auto-clasifica antes de enviar). Reglas:
      - El renglón declara 2+ incidencias -> INCIDENCIA_MIXTA.
      - Un renglón con condición declarada -> esa condición manda.
      - Si no hay condición, la diferencia de cantidad decide: FALTANTE/SOBRANTE.
      - Ninguna incidencia -> CONFORME.
    """
    affected = []
    for it in processed_items:
        cond = it.get("item_condition", "CONFORME")
        rec_qty = Decimal(str(it["received_quantity"]))
        dispatched_qty = Decimal(str(it["quantity"]))
        if cond != "CONFORME":
            affected.append(cond)
        elif rec_qty < dispatched_qty:
            affected.append("FALTANTE_CONTEO")
        elif rec_qty > dispatched_qty:
            affected.append("SOBRANTE_EXCEDENTE")
    if len(affected) >= 2:
        return "INCIDENCIA_MIXTA"
    if len(affected) == 1:
        return affected[0]
    return "CONFORME"


def _creditable_return_qty(movement, product_id, lot_number, effective_stock_qty):
    """Cuánto acreditar en el DESTINO al recibir un RETORNO_EMERGENCIA.

    La bandeja de arbitraje crea la devolución automática (RETORNO_EMERGENCIA)
    al resolver una disputa, y puede traer dos familias de mercancía:

      - Insumos ERRÓNEOS (entregados por error, nunca estuvieron en la guía):
        no se debitaron del origen al despachar, por lo que recibirlos de vuelta
        NO debe acreditarlos puntualmente. Acreditarlo sería un doble asiento
        (el inventario del origen nunca los perdió) -> stock fantasma.
      - Mercancía que SÍ venía en la guía y se devuelve (rechazo total o
        faltante reintegrado): el origen la debitó al despachar y aún no la
        recupera; aquí solo se repone lo pendiente (despachado - recibido
        conforme), contrastado con el despacho original.

    Sin vínculo a disputa (return_of_dispute_id NULL) se acredita nada: más
    seguro que arriesgar un asiento duplicado.
    """
    original_movement_id = movement.get("return_of_dispute_id")
    if not original_movement_id:
        return Decimal("0.00")

    outstanding = MovementReceptionRepository.get_outstanding_dispatch_debit(
        original_movement_id, product_id, lot_number
    )
    return min(effective_stock_qty, outstanding)


class MovementReceptionService:

    @staticmethod
    def get_reception_data(movement_id, user_location_ids, user_role_id):
        movement = MovementReceptionRepository.get_movement_by_id(movement_id)
        if not movement:
            return None, "Traslado no encontrado."

        if str(movement["status"]).upper() != "EN_TRANSITO":
            return None, f"El traslado #{movement_id} no está en tránsito (Estado actual: {movement['status']})."

        if user_role_id != 1 and movement["destination_location_id"] not in user_location_ids:
            return None, "No tiene permisos para recibir cargas destinadas a otra sede."

        details = MovementReceptionRepository.get_movement_details(movement_id)

        # 'Techo' de sobrante: el inventario NO lleva stock por lote, así que el
        # techo razonable es el stock físico actual del PRODUCTO en el origen (el
        # Central). Un excedente no puede superar lo que el origen conserva. Se
        # adjunta por renglón (solo lectura; no altera el flujo de Mariuska).
        origin_id = movement["origin_location_id"]
        # Los rows de get_movement_details son mappings; los convertimos a dict
        # para poder adjuntar origin_stock.
        details_dicts = []
        for d in details:
            item = dict(d._mapping if hasattr(d, "_mapping") else d)
            item["origin_stock"] = float(
                MovementReceptionRepository.get_inventory_quantity(origin_id, d.product_id)
            )
            details_dicts.append(item)

        return {"movement": movement, "details": details_dicts}, None

    @staticmethod
    def get_lot_expiration(product_id, lot_number):
        """Verifica si un serial/lote existe en la BD y, si lo hace, su vencimiento.

        Devuelve un dict con:
          - exists: True si el lote ya circuló por depósito/compras.
          - expiration_date: vencimiento conocido (str 'YYYY-MM-DD') o None.
        Permite al muelle avisar "este serial no existe" de inmediato, sin esperar a
        que el arbitraje lo confirme.
        """
        if not product_id or not lot_number or not str(lot_number).strip():
            return {"exists": False, "expiration_date": None}
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return {"exists": False, "expiration_date": None}
        exists = MovementReceptionRepository.lot_exists(product_id, lot_number)
        expiration = MovementReceptionRepository.get_expiration_for_lot(product_id, lot_number)
        return {"exists": exists, "expiration_date": expiration}

    @staticmethod
    def process_reception(movement_id, user_id, user_role_id, user_location_ids, payload):
        movement = MovementReceptionRepository.get_movement_by_id(movement_id)
        if not movement:
            return False, "Traslado no encontrado."

        if str(movement["status"]).upper() != "EN_TRANSITO":
            return False, f"El traslado no puede ser recibido con estatus '{movement['status']}'."

        if user_role_id != 1 and movement["destination_location_id"] not in user_location_ids:
            return False, "Operación denegada. Solo la sede destino autorizada puede recibir esta carga."

        raw_details = MovementReceptionRepository.get_movement_details(movement_id)
        details_map = {d.id: d for d in raw_details}

        is_valid, validation_res = validate_reception_payload(payload, details_map)
        if not is_valid:
            return False, validation_res

        novelty_type = validation_res["novelty_type"]
        notes = validation_res["notes"]
        processed_items = validation_res["items"]
        erroneous_products = validation_res.get("erroneous_products", [])
        has_discrepancy = validation_res["has_discrepancy"]

        # Validación de los LOTES DEL SOBRANTE (el excedente puede venir de 1..N lotes).
        # El lote del sobrante es OBLIGATORIO y debe EXISTIR en el sistema (mismo
        # criterio que el insumo erróneo); además, la suma de las cantidades de los
        # lotes debe cuadrar con el excedente total. Se valida aquí (con acceso a BD)
        # porque el validador es una función pura sin repositorio.
        for item in processed_items:
            rec_qty = Decimal(str(item["received_quantity"]))
            dispatched_qty = Decimal(str(item["quantity"]))
            extra_units = rec_qty - dispatched_qty
            if extra_units <= Decimal("0.001"):
                continue
            product_id = item["product_id"]
            surplus_lots = item.get("surplus_lots") or []
            named_lots = [sl for sl in surplus_lots if sl.get("lot")]
            if not named_lots:
                return False, (
                    f"El sobrante de '{item.get('product_name') or 'el insumo'}' debe declarar de qué "
                    "lote del sistema proviene. Escriba al menos un lote en la lista de lotes del sobrante."
                )
            # Red de seguridad (espejo del frontend): una CANTIDAD declarada sin lote
            # sería descartada en silencio al sumar (solo se suman lotes con nombre), lo
            # que asentaría menos de lo declarado. Se rechaza con un mensaje claro en vez
            # de ignorarla. La UI ya lo bloquea; aquí se garantiza por API/script.
            for sl in surplus_lots:
                if sl.get("lot"):
                    continue
                try:
                    orphan_qty = Decimal(str(sl.get("quantity") or 0) or 0)
                except (InvalidOperation, TypeError, ValueError):
                    orphan_qty = Decimal("0.00")
                if orphan_qty > Decimal("0.00"):
                    return False, (
                        f"El sobrante de '{item.get('product_name') or 'el insumo'}' declara una cantidad "
                        f"({orphan_qty}) sin indicar de qué lote del sistema proviene. "
                        "Escriba el lote para cada cantidad, o vacíe la fila sin lote."
                    )
            unknown_lots = []
            surplus_sum = Decimal("0.00")
            for sl in named_lots:
                lot_val = str(sl.get("lot") or "").strip()
                try:
                    surplus_sum += Decimal(str(sl.get("quantity") or 0) or 0)
                except (InvalidOperation, TypeError, ValueError):
                    return False, (
                        f"Lote '{lot_val}' del sobrante de '{item.get('product_name') or 'el insumo'}': "
                        "la cantidad no es numérica válida."
                    )
                if not MovementReceptionRepository.lot_exists(product_id, lot_val):
                    unknown_lots.append(lot_val)
            if unknown_lots:
                return False, (
                    "Uno o más lotes del sobrante no están registrados en el sistema "
                    f"({', '.join(unknown_lots)}). Escriba un lote existente para que el excedente quede trazable."
                )
            if abs(surplus_sum - extra_units) > Decimal("0.01"):
                return False, (
                    f"La suma de las cantidades de los lotes del sobrante de '{item.get('product_name') or 'el insumo'}' "
                    f"({surplus_sum}) no coincide con el excedente total (+{extra_units}). "
                    "Ajuste las cantidades de cada lote para que sumen exactamente el sobrante."
                )

        # Los insumos NO SOLICITADOS (erróneos) deben existir en el catálogo. Si un id
        # no corresponde a un producto real, la recepción no podría auditarse y la bandeja
        # de arbitraje intentaría crear inventario con una FK huérfana al resolver.
        if erroneous_products:
            err_ids = {int(err_p["product_id"]) for err_p in erroneous_products}
            known_ids = {
                row[0] for row in db.session.query(Product.id).filter(Product.id.in_(err_ids)).all()
            }
            unknown_ids = sorted(err_ids - known_ids)
            if unknown_ids:
                return False, (
                    "Uno de los insumos no solicitados no existe en el catálogo "
                    f"(IDs: {', '.join(map(str, unknown_ids))}). Revise la selección."
                )

        # DERIVAR vencimiento desde el sistema cuando el lote es reconocido.
        # Si el sistema conoce el vencimiento real del lote, se usa ese
        # (evita que el operario forge una fecha distinta). Si el lote no
        # está registrado en BD, se conserva el valor enviado (en la UI el
        # campo es readonly y se llena solo, pero por API/script podría
        # venir un valor diferente).
        for err_p in erroneous_products:
            pid = int(err_p["product_id"])
            lot = str(err_p.get("lot_number") or "").strip()
            if lot:
                sys_exp = MovementReceptionRepository.get_expiration_for_lot(pid, lot)
                if sys_exp:
                    err_p["expiration_date"] = sys_exp

        # LÓGICA CORREGIDA: Prioridad absoluta al novelty_type seleccionado/enviado.
        # Si se envía CONFORME pero los renglones revelan discrepancias (caso solo
        # alcanzable por API/script, el JS ya auto-clasifica), se deriva el estatus
        # REAL de las diferencias en vez de etiquetarlo con el genérico
        # NOVEDAD_FALTANTE (que hasta un EXCESO convertía en "faltante").
        final_status = "COMPLETADO"
        derived_status = None
        if novelty_type and novelty_type != "CONFORME":
            final_status = novelty_type
        elif has_discrepancy or len(erroneous_products) > 0:
            derived_status = _derive_auto_novelty(processed_items)
            if derived_status == "CONFORME":
                derived_status = "PRODUCTO_ERRONEO" if erroneous_products else "COMPLETADO"
            final_status = derived_status

        # REGLA DE VENCIMIENTO PRÓXIMO (decisión de diseño):
        # Si la ÚNICA condición es el vencimiento próximo (cantidades exactas y sin
        # insumos erróneos), la mercancía ingresa igual que una recepción conforme:
        # se acredita en destino y solo queda la alerta FEFO en la auditoría. NO va a
        # la bandeja de arbitraje. Si además hay faltante/sobrante real o erróneos,
        # entonces sí es una incidencia y el movimiento queda para arbitraje.
        near_expiry_credits_like_conforme = (
            final_status == "VENCIMIENTO_PROXIMO"
            and not erroneous_products
            and all(
                Decimal(str(it["received_quantity"])) == Decimal(str(it["quantity"]))
                for it in processed_items
            )
        )
        if near_expiry_credits_like_conforme:
            final_status = "COMPLETADO"

        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            audit_discrepancies = []
            specific_novelty_map = {}

            for item in processed_items:
                detail_id = item["detail_id"]
                product_id = item["product_id"]
                rec_qty = Decimal(str(item["received_quantity"]))
                mis_qty = Decimal(str(item["missing_quantity"]))
                dispatched_qty = Decimal(str(item["quantity"]))
                item_cond = item.get("item_condition", "CONFORME")

                MovementReceptionRepository.update_detail_quantities(detail_id, rec_qty, mis_qty)
                MovementReceptionRepository.get_or_create_inventory(movement["origin_location_id"], product_id)
                MovementReceptionRepository.get_or_create_inventory(movement["destination_location_id"], product_id)

                # Calcular unidades extra si las hay
                if item_cond == 'SOBRANTE_EXCEDENTE' or rec_qty > dispatched_qty:
                    extra_units = float(rec_qty - dispatched_qty)
                else:
                    extra_units = 0.0

                # LÓGICA DIFERENCIADA:
                # Si el traslado es COMPLETADO (sin novedades), liberamos el tránsito y acreditamos
                # en destino la cantidad conforme (min(recibido, autorizado)).
                # Si hay discrepancia/novedad, NO se acredita nada en destino todavía (eso lo decide
                # el administrador en la bandeja de disputas). Solo se libera el tránsito que
                # resguardaba la salida, para no dejar stock bloqueado en el origen.
                if final_status == "COMPLETADO":
                    effective_stock_qty = min(rec_qty, dispatched_qty)
                    if effective_stock_qty > Decimal("0.00"):
                        MovementReceptionRepository.update_origin_transit(
                            movement["origin_location_id"], product_id, effective_stock_qty
                        )
                        if movement["type"] == "RETORNO_EMERGENCIA":
                            # BUGFIX doble conteo: un retorno solo repone lo que el
                            # despacho original dejó pendiente (despachado menos
                            # recibido conforme). Lo erróneo (fuera de guía) nunca
                            # se debitó del origen, así que no se acredita de vuelta.
                            creditable_qty = _creditable_return_qty(
                                movement, product_id, item["lot_number"], effective_stock_qty
                            )
                        else:
                            creditable_qty = effective_stock_qty
                        if creditable_qty > Decimal("0.00"):
                            MovementReceptionRepository.increment_destination_stock(
                                movement["destination_location_id"], product_id, creditable_qty
                            )
                else:
                    # En caso de novedad/disputa liberamos el tránsito COMPLETO que se despachó
                    # (el movimiento quedó "en disputa", no EN_TRANSITO, así que el tránsito que
                    # resguardaba esa salida debe liberarse para no dejar stock bloqueado). Esto NO
                    # acredita nada en destino todavía: el destino final lo decide resolve_dispute en
                    # la bandeja de arbitraje, que reacomoda el current/transit según la resolución.
                    if dispatched_qty > Decimal("0.00"):
                        MovementReceptionRepository.update_origin_transit(
                            movement["origin_location_id"], product_id, dispatched_qty
                        )

                # Observación del muelle por renglón: se deriva de la diferencia física y de la
                # condición declarada. Se reutiliza tanto en discrepancies (lo que consume la
                # bandeja de arbitraje) como en items (bitácora detallada).
                item_diff = float(rec_qty) - float(dispatched_qty)
                if item_diff < -0.001:
                    specific_novelty = "FALTANTE"
                elif item_diff > 0.001:
                    specific_novelty = "SOBRANTE"
                elif item_cond != "CONFORME" and item_cond not in ("SOBRANTE_EXCEDENTE", "FALTANTE_CONTEO"):
                    specific_novelty = item_cond
                else:
                    specific_novelty = "CONFORME"

                specific_novelty_map[detail_id] = specific_novelty

                audit_discrepancies.append({
                    "detail_id": detail_id,
                    "product_id": product_id,
                    "lot_number": item["lot_number"],
                    "type": item_cond,
                    "authorized_qty": float(dispatched_qty),
                    "physical_received_qty": float(rec_qty),
                    "extra_units": extra_units,
                    "missing_qty": float(mis_qty),
                    "observed_physical_lot": item.get("observed_physical_lot"),
                    "observed_physical_expiration": item.get("observed_physical_expiration"),
                    "surplus_lots": item.get("surplus_lots") or [],
                    "notes": specific_novelty
                })

            MovementReceptionRepository.finalize_movement(movement_id, final_status, user_id)

            audit_event = "RECEPCION_CONFORME"
            severity = "NORMAL"
            
            if final_status != "COMPLETADO":
                audit_event = "RECEPCION_NOVEDAD"
                severity = "ALERTA"
                if any(it.get("item_condition") in ['INCIDENCIA_TEMPERATURA', 'VIOLACION_CUSTODIA', 'VENCIMIENTO_PROXIMO'] for it in processed_items):
                    audit_event = "RECEPCION_INCIDENCIA_CALIDAD"

            audit_items = []
            for item in processed_items:
                detail_obj = details_map[item["detail_id"]]
                item_cond = item.get("item_condition", "CONFORME")

                specific_novelty = specific_novelty_map[item["detail_id"]]

                audit_items.append({
                    "detail_id": item["detail_id"],
                    "product_id": item["product_id"],
                    "sku": detail_obj.sku,
                    "product_name": detail_obj.product_name,
                    "lot_number": item["lot_number"],
                    "observed_physical_lot": item.get("observed_physical_lot"),
                    "observed_physical_expiration": item.get("observed_physical_expiration"),
                    "expiration_date": str(item["expiration_date"]) if item["expiration_date"] else None,
                    "dispatched_qty": float(item["quantity"]),
                    "received_qty": float(item["received_quantity"]),
                    "missing_qty": float(item["missing_quantity"]),
                    "item_condition": item_cond,
                    "specific_novelty": specific_novelty
                })

            erroneous_audit_list = []
            for err_p in erroneous_products:
                p_obj = db.session.get(Product, err_p["product_id"])
                # El VENCIMIENTO del insumo erróneo se deriva del sistema cuando
                # el lote es reconocido (evita que el operario forge una fecha).
                # Si el lote no está registrado en BD, se conserva el valor
                # enviado por el cliente como mejor estimación disponible.
                err_lot = err_p.get("lot_number")
                system_expiration = MovementReceptionRepository.get_expiration_for_lot(
                    int(err_p["product_id"]), err_lot
                ) if err_lot else None
                erroneous_audit_list.append({
                    "product_id": p_obj.id if p_obj else err_p["product_id"],
                    "sku": p_obj.sku if p_obj else "N/A",
                    "product_name": p_obj.name if p_obj else "Insumo Desconocido",
                    "quantity_delivered": float(err_p["quantity"]),
                    "lot_number": err_lot,
                    "expiration_date": system_expiration or err_p.get("expiration_date")
                })

            changed_data = {
                "movement_id": movement_id,
                "event": audit_event,
                "novelty_type": novelty_type,
                # Estatus EFECTIVO con el que se finalizó el movimiento (puede derivarse
                # de las diferencias si el payload llegó CONFORME por API/script). Se
                # registra aparte para que la bitácora refleje el estado real.
                "final_status": final_status,
                "origin_location_id": movement["origin_location_id"],
                "destination_location_id": movement["destination_location_id"],
                "items": audit_items,
                "discrepancies": audit_discrepancies,
                "erroneous_products_delivered": erroneous_audit_list,
                "notes": notes,
                "received_by_user_id": user_id,
                "timestamp": now.isoformat() + "Z"
            }

            MovementReceptionRepository.insert_audit_log({
                "affected_table": "movements",
                "action": audit_event,
                "severity": severity,
                "user_id": user_id,
                "timestamp": now,
                "changed_data": json.dumps(changed_data),
                "location_id": movement["destination_location_id"]
            })

            db.session.commit()
            return True, "Recepción procesada exitosamente."

        except Exception as e:
            db.session.rollback()
            return False, f"Error transaccional al procesar recepción: {str(e)}"