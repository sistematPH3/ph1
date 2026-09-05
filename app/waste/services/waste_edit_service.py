from datetime import datetime, timedelta
from app.waste.repositories.waste_edit_repository import WasteEditRepository
from app.waste.requests.waste_edit_validators import validate_edit_payload, validate_reversal_payload

class WasteEditService:

    @staticmethod
    def get_waste_for_edit(waste_id, user_id, is_admin):
        waste = WasteEditRepository.get_waste_by_id(waste_id)
        if not waste:
            return None, "La merma indicada no existe."

        now = datetime.utcnow()
        created_at = waste.date or now
        time_elapsed = now - created_at

        can_edit = False
        can_revert = False

        if waste.status == "PENDIENTE":
            if is_admin:
                if time_elapsed <= timedelta(days=30):
                    can_edit = True
            else:
                if waste.user_id == user_id and time_elapsed <= timedelta(hours=24):
                    can_edit = True

        elif waste.status == "APROBADO":
            if is_admin:
                can_revert = True

        if not can_edit and not can_revert:
            return None, "No tiene permisos o la ventana de tiempo para gestionar esta merma ha expirado."

        is_central = (waste.location_id == 1)
        available_types = WasteEditRepository.get_active_waste_types(is_central)

        location_name = WasteEditRepository.get_location_name(waste.location_id)
        author_name = WasteEditRepository.get_user_name(waste.user_id)

        product_ids = [d.product_id for d in waste.details]
        products_map = WasteEditRepository.get_products_map(product_ids)

        wt = waste.waste_type
        waste_type_name = wt.name if wt else "N/A"

        lines = []
        for d in waste.details:
            p = products_map.get(d.product_id)
            product_name = p.name if p else f"Producto #{d.product_id}"
            sku = p.sku if p else "N/A"
            unit = p.unit_of_measure if p else "uds"
            cur_exp = d.expiration_date.strftime("%Y-%m-%d") if d.expiration_date else ""

            lots = WasteEditRepository.get_lots_for_product(waste.location_id, d.product_id)
            matched_lot = next((l for l in lots if l["lot_number"] == d.lot_number), None)
            if not matched_lot:
                lots.insert(0, {
                    "lot_number": d.lot_number,
                    "expiration_date": cur_exp,
                    "stock": float(d.quantity)
                })
                current_max_stock = float(d.quantity)
            else:
                current_max_stock = float(matched_lot.get("stock", d.quantity))

            lines.append({
                "id": d.id,
                "product_id": d.product_id,
                "product_name": product_name,
                "sku": sku,
                "unit": unit,
                "lot_number": d.lot_number,
                "expiration_date": cur_exp,
                "available_lots": lots,
                "current_max_stock": current_max_stock,
                "quantity": float(d.quantity),
                "unit_cost": float(d.unit_cost),
                "subtotal_cost": float(d.subtotal_cost)
            })

        return {
            "id": waste.id,
            "status": waste.status,
            "location_name": location_name,
            "waste_type_id": waste.waste_type_id,
            "waste_type_name": waste_type_name,
            "notes": waste.notes or "",
            "date": waste.date.strftime("%d/%m/%Y %H:%M") if waste.date else "",
            "evidence_url": waste.evidence_url or "",
            "author_name": author_name,
            "lines": lines,
            "can_edit": can_edit,
            "can_revert": can_revert,
            "waste_types": [
                {"id": t.id, "name": t.name, "severity": t.severity}
                for t in available_types
            ]
        }, None

    @staticmethod
    def edit_pending_waste(waste_id, payload, user_id, is_admin):
        waste = WasteEditRepository.get_waste_for_update(waste_id)
        if not waste:
            return {"success": False, "message": "Merma no encontrada."}, 404

        if waste.status != "PENDIENTE":
            return {"success": False, "message": "Solo se pueden editar mermas en estado PENDIENTE."}, 400

        now = datetime.utcnow()
        created_at = waste.date or now
        time_elapsed = now - created_at

        if is_admin:
            if time_elapsed > timedelta(days=30):
                return {"success": False, "message": "El plazo de corrección para administradores (30 días) ha expirado."}, 403
        else:
            if waste.user_id != user_id:
                return {"success": False, "message": "No tienes autorización para modificar esta merma."}, 403
            if time_elapsed > timedelta(hours=24):
                return {"success": False, "message": "La ventana de corrección de 24 horas ha expirado."}, 403

        validation = validate_edit_payload(payload)
        if not validation["is_valid"]:
            return {"success": False, "errors": validation["errors"]}, 400

        for line in validation["data"]["lines"]:
            lots = WasteEditRepository.get_lots_for_product(waste.location_id, line["product_id"])
            matched = next((l for l in lots if l["lot_number"] == line["lot_number"]), None)
            if matched and "stock" in matched:
                if float(line["quantity"]) > float(matched["stock"]):
                    return {
                        "success": False,
                        "message": f"La cantidad asignada ({line['quantity']}) excede la existencia disponible en el lote {line['lot_number']} ({matched['stock']})."
                    }, 400

        WasteEditRepository.save_pending_edit(waste, validation["data"], user_id)
        return {"success": True, "message": f"Merma #{waste.id} actualizada satisfactoriamente."}, 200

    @staticmethod
    def revert_approved_waste(waste_id, payload, user_id, is_admin):
        if not is_admin:
            return {"success": False, "message": "Solo un Administrador puede revertir mermas aprobadas."}, 403

        waste = WasteEditRepository.get_waste_by_id(waste_id)
        if not waste:
            return {"success": False, "message": "Merma no encontrada."}, 404

        if waste.status != "APROBADO":
            return {"success": False, "message": f"Solo se pueden revertir mermas en estado APROBADO (Estado actual: {waste.status})."}, 400

        validation = validate_reversal_payload(payload)
        if not validation["is_valid"]:
            return {"success": False, "errors": validation["errors"]}, 400

        WasteEditRepository.execute_reversion(waste_id, user_id, validation["reason"])
        return {
            "success": True,
            "message": f"Merma #{waste_id} revertida con éxito. El inventario ha sido restituido en la sede."
        }, 200