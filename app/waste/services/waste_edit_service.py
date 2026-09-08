from datetime import datetime, timedelta
from decimal import Decimal

from app.waste.repositories.waste_edit_repository import WasteEditRepository
from app.waste.repositories.register_waste_repository import RegisterWasteRepository
from app.waste.requests.waste_edit_validators import validate_edit_payload, validate_reversal_payload
from app.waste.services.register_waste_service import user_can_access_location


def _fmt_quantity(value):
    """Formatea cantidades quitando ceros decimales sobrantes (2.00 -> 2)."""
    try:
        d = Decimal(str(value))
    except Exception:
        return value
    if d == d.to_integral_value():
        return int(d)
    return float(d.quantize(Decimal("0.01")))
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
            elif user_can_access_location(user_id, waste.location_id):
                can_edit = True

        elif waste.status == "APROBADO":
            if is_admin:
                can_revert = True

        if not can_edit and not can_revert:
            message = (
                "No tiene permisos o la ventana de tiempo para gestionar esta merma ha expirado."
                if is_admin else "No tienes permisos para modificar mermas de esta sede."
            )
            return None, message

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

            eff_type = d.waste_type or waste.waste_type
            line_type_id = d.waste_type_id or waste.waste_type_id
            line_type_name = eff_type.name if eff_type else "N/A"
            line_type_code = getattr(eff_type, "code", None) or ""
            waste_limit = p.waste_limit if p else None
            excede_limite = (
                (waste_limit is not None)
                and float(d.quantity or 0) > float(waste_limit)
            )

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
                "current_max_stock": _fmt_quantity(current_max_stock),
                "quantity": _fmt_quantity(d.quantity),
                "unit_cost": float(d.unit_cost),
                "subtotal_cost": float(d.subtotal_cost),
                "waste_type_id": line_type_id,
                "waste_type_name": line_type_name,
                "waste_type_code": line_type_code,
                "waste_limit": float(waste_limit) if waste_limit is not None else None,
                "excede_limite": excede_limite,
                "status": d.status or "PENDIENTE",
                "editable": bool(not d.status or d.status == "PENDIENTE"),
                "decided": bool(d.status and d.status != "PENDIENTE"),
                "resolution_reason": d.resolution_reason or "",
                "evidence_url": d.evidence_url or "",
                "photos": [
                    p.photo_url
                    for p in sorted(d.photos, key=lambda ph: (ph.position or 1, ph.id))
                ] if d.photos else []
            })

        return {
            "id": waste.id,
            "status": waste.status,
            "location_id": waste.location_id,
            "location_name": location_name,
            "waste_type_id": waste.waste_type_id,
            "waste_type_name": waste_type_name,
            "waste_type_code": getattr(waste.waste_type, "code", None) or "",
            "is_vencido": bool(getattr(waste.waste_type, "code", None) == "VENCIDO"),
            "total_quantity": _fmt_quantity(waste.total_quantity),
            "notes": waste.notes or "",
            "date": waste.date.strftime("%d/%m/%Y %H:%M") if waste.date else "",
            "evidence_url": waste.evidence_url or "",
            "author_name": author_name,
            "lines": lines,
            "can_edit": can_edit,
            "can_revert": can_revert,
            "waste_types": [
                {"id": t.id, "name": t.name, "severity": t.severity, "code": t.code or ""}
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
        elif not user_can_access_location(user_id, waste.location_id):
            return {"success": False, "message": "No tienes permisos para modificar mermas de esta sede."}, 403

        validation = validate_edit_payload(payload)
        if not validation["is_valid"]:
            return {"success": False, "errors": validation["errors"]}, 400

        # Reserva actual congelada por las líneas PENDIENTES de esta merma.
        # Al reemplazarlas hay que ajustar reserved_quantity por la diferencia.
        old_pending = {}
        for d in waste.details:
            if not d.status or d.status == "PENDIENTE":
                old_pending[d.product_id] = old_pending.get(d.product_id, 0.0) + float(d.quantity or 0)

        header_type_id = validation["data"]["waste_type_id"]
        if not header_type_id and validation["data"]["lines"]:
            header_type_id = validation["data"]["lines"][0].get("waste_type_id")
        new_type = RegisterWasteRepository.get_waste_type_by_id(header_type_id)
        if not new_type or not new_type.is_active:
            return {"success": False, "message": "El tipo de merma seleccionado no es válido."}, 400
        if int(waste.location_id) == 1 and not new_type.applies_central \
                and getattr(new_type, "code", None) != 'VENCIDO':
            return {
                "success": False,
                "message": "Este tipo de merma no aplica a la Sede Central."
            }, 400

        header_vencido = bool(getattr(new_type, "code", None) == "VENCIDO")

        # Cada línea puede traer SU PROPIO tipo de merma. Sin él, hereda el de
        # la cabecera. Se resuelve y valida para usar VENCIDO por línea.
        for line in validation["data"]["lines"]:
            line_type_id = line.get("waste_type_id") or validation["data"]["waste_type_id"]
            line_type = RegisterWasteRepository.get_waste_type_by_id(line_type_id)
            if not line_type or not line_type.is_active:
                return {
                    "success": False,
                    "message": "El tipo de merma de una de las líneas no es válido."
                }, 400
            if int(waste.location_id) == 1 and not line_type.applies_central \
                    and getattr(line_type, "code", None) != 'VENCIDO':
                return {
                    "success": False,
                    "message": (
                        f'El tipo de merma "{line_type.name}" de una de las '
                        "líneas no aplica a la Sede Central."
                    )
                }, 400
            line["_waste_type"] = line_type
            line["waste_type_id"] = line_type.id

        lineas_vencido = any(
            getattr(l["_waste_type"], "code", None) == "VENCIDO"
            for l in validation["data"]["lines"]
        )
        vencidos = set()
        if header_vencido or lineas_vencido:
            try:
                for v in RegisterWasteRepository.get_expired_lots(waste.location_id):
                    vencidos.add((int(v["product_id"]), str(v["lot_number"]).strip()))
            except Exception:
                vencidos = set()

        # La edición solo ajusta los productos ya registrados en la merma; no
        # se pueden AGREGAR productos nuevos (la reserva se ajusta por línea).
        original_pending_products = {
            int(d.product_id) for d in waste.details
            if not d.status or d.status == "PENDIENTE"
        }
        for line in validation["data"]["lines"]:
            if int(line["product_id"]) not in original_pending_products:
                product = RegisterWasteRepository.get_product_by_id(line["product_id"])
                nombre = product.name if product else f"ID {line['product_id']}"
                return {
                    "success": False,
                    "message": (
                        f"No se puede agregar el producto {nombre} al editar la "
                        "merma; solo se ajustan los productos ya registrados."
                    )
                }, 400

        used_by_lot = {}
        decididos = {
            (int(dd.product_id), str(dd.lot_number or "").strip())
            for dd in waste.details
            if dd.status and dd.status != "PENDIENTE"
        }
        for line in validation["data"]["lines"]:
            pid = line["product_id"]
            lot = line["lot_number"]

            if (int(pid), lot) in decididos:
                product = RegisterWasteRepository.get_product_by_id(pid)
                nombre = product.name if product else f"ID {pid}"
                return {
                    "success": False,
                    "message": (
                        f"El producto {nombre} (lote {lot}) ya tomó decisión de "
                        "resolución y no puede modificarse."
                    )
                }, 400

            if line["_waste_type"].code == 'VENCIDO' and (pid, lot) not in vencidos:
                product = RegisterWasteRepository.get_product_by_id(pid)
                nombre = product.name if product else f"ID {pid}"
                return {
                    "success": False,
                    "message": (
                        f"El lote {lot} de {nombre} no está vencido o no existe una "
                        "existencia vencida en esta sede. Con el tipo VENCIDO solo se "
                        "pueden mermar lotes cuya fecha de vencimiento ya haya pasado."
                    )
                }, 400

            lots = WasteEditRepository.get_lots_for_product(waste.location_id, pid)
            matched = next((l for l in lots if l["lot_number"] == lot), None)
            stock = float(matched["stock"]) if matched else 0.0

            acumulado_lote = used_by_lot.get((pid, lot), 0.0) + float(line["quantity"])
            if acumulado_lote > stock + 1e-9:
                nombre_lote = matched["lot_number"] if matched else lot
                return {
                    "success": False,
                    "message": (
                        f"La cantidad asignada al lote {nombre_lote} ({acumulado_lote:.2f} "
                        f"unidades en este ticket) supera su saldo disponible de {stock:.2f}."
                    )
                }, 400
            used_by_lot[(pid, lot)] = acumulado_lote

            unit_cost = RegisterWasteRepository.get_unit_cost(pid, lot)
            line["unit_cost"] = unit_cost
            line["subtotal_cost"] = (line["quantity"] * unit_cost).quantize(Decimal("0.01"))
            line["expiration_date"] = RegisterWasteRepository.get_lot_expiration_date(pid, lot, waste.location_id)

        # Ajuste de reserva por el delta entre las líneas pendientes nuevas y
        # las anteriores. Valida primero que la nueva reserva no supere el
        # stock físico disponible (current - transit).
        new_pending = {}
        for line in validation["data"]["lines"]:
            new_pending[line["product_id"]] = new_pending.get(line["product_id"], 0.0) + float(line["quantity"])

        for product_id in set(old_pending) | set(new_pending):
            delta = new_pending.get(product_id, 0.0) - old_pending.get(product_id, 0.0)
            if abs(delta) < 1e-9:
                continue
            inv = RegisterWasteRepository.get_inventory_item_for_update(product_id, waste.location_id)
            if inv is None:
                product = RegisterWasteRepository.get_product_by_id(product_id)
                nombre = product.name if product else f"ID {product_id}"
                return {
                    "success": False,
                    "message": f"No existe inventario para {nombre} en esta sede."
                }, 400
            disponible_fisico = float(inv.current_quantity or 0) - float(inv.transit_quantity or 0)
            nueva_reserva = float(inv.reserved_quantity or 0) + delta
            if nueva_reserva > disponible_fisico + 1e-9:
                product = RegisterWasteRepository.get_product_by_id(product_id)
                nombre = product.name if product else f"ID {product_id}"
                return {
                    "success": False,
                    "message": (
                        f"Stock insuficiente para {nombre}: la nueva cantidad "
                        "mermada dejaría la disponibilidad por debajo de cero."
                    )
                }, 400
            inv.reserved_quantity = round(max(0.0, nueva_reserva), 2)

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