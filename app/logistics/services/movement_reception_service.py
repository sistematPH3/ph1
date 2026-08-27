import json
from decimal import Decimal
from datetime import datetime
from app import db
from app.logistics.repositories.movement_reception_repository import MovementReceptionRepository
from app.logistics.requests.movement_reception_validators import validate_reception_payload

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
        return {"movement": movement, "details": details}, None

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
        has_discrepancy = validation_res["has_discrepancy"]

        final_status = "COMPLETADO"
        if has_discrepancy or novelty_type in ['FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE', 'PRODUCTO_ERRONEO', 'RECHAZO_POR_ESPACIO']:
            final_status = "NOVEDAD_FALTANTE"

        try:
            for item in processed_items:
                detail_id = item["detail_id"]
                product_id = item["product_id"]
                rec_qty = Decimal(str(item["received_quantity"]))
                mis_qty = Decimal(str(item["missing_quantity"]))
                dispatched_qty = Decimal(str(item["quantity"]))

                MovementReceptionRepository.update_detail_quantities(detail_id, rec_qty, mis_qty)
                MovementReceptionRepository.get_or_create_inventory(movement["origin_location_id"], product_id)
                MovementReceptionRepository.get_or_create_inventory(movement["destination_location_id"], product_id)

                effective_stock_qty = min(rec_qty, dispatched_qty)

                if effective_stock_qty > Decimal("0.00"):
                    MovementReceptionRepository.update_origin_transit(
                        movement["origin_location_id"], product_id, effective_stock_qty
                    )
                    MovementReceptionRepository.increment_destination_stock(
                        movement["destination_location_id"], product_id, effective_stock_qty
                    )

            MovementReceptionRepository.finalize_movement(movement_id, final_status, user_id)

            audit_event = "RECEPCION_CONFORME"
            severity = "NORMAL"
            if final_status == "NOVEDAD_FALTANTE":
                audit_event = "RECEPCION_NOVEDAD"
                severity = "ALERTA"
            elif novelty_type in ['INCIDENCIA_TEMPERATURA', 'VIOLACION_CUSTODIA', 'VENCIMIENTO_PROXIMO', 'LOTE_NO_COINCIDE']:
                audit_event = "RECEPCION_INCIDENCIA_CALIDAD"
                severity = "ALERTA"

            audit_items = []
            for item in processed_items:
                detail_obj = details_map[item["detail_id"]]
                audit_items.append({
                    "product_id": item["product_id"],
                    "sku": detail_obj.sku,
                    "product_name": detail_obj.product_name,
                    "lot_number": item["lot_number"],
                    "expiration_date": str(item["expiration_date"]) if item["expiration_date"] else None,
                    "dispatched_qty": float(item["quantity"]),
                    "received_qty": float(item["received_quantity"]),
                    "missing_qty": float(item["missing_quantity"])
                })

            changed_data = {
                "movement_id": movement_id,
                "event": audit_event,
                "novelty_type": novelty_type,
                "origin_location_id": movement["origin_location_id"],
                "destination_location_id": movement["destination_location_id"],
                "items": audit_items,
                "notes": notes,
                "received_by_user_id": user_id,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            MovementReceptionRepository.insert_audit_log({
                "affected_table": "movements",
                "action": audit_event,
                "severity": severity,
                "user_id": user_id,
                "timestamp": datetime.utcnow(),
                "changed_data": json.dumps(changed_data),
                "location_id": movement["destination_location_id"]
            })

            db.session.commit()
            return True, "Recepción procesada exitosamente."

        except Exception as e:
            db.session.rollback()
            return False, f"Error transaccional al procesar recepción: {str(e)}"