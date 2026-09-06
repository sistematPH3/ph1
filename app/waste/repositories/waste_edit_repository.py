from app.time_utils import current_ve_time
from decimal import Decimal
from sqlalchemy import text
from app.extensions import db
from app.models.waste_model import Waste, WasteDetail, WasteType, AuditLog
from app.models.inventory_model import Inventory, Product

class WasteEditRepository:

    @staticmethod
    def get_waste_by_id(waste_id):
        return db.session.query(Waste).filter(Waste.id == waste_id).first()

    @staticmethod
    def get_location_name(location_id):
        if not location_id:
            return "N/A"
        row = db.session.execute(
            text("SELECT name FROM locations WHERE id = :id"),
            {"id": location_id}
        ).fetchone()
        return row[0] if row else "N/A"

    @staticmethod
    def get_user_name(user_id):
        if not user_id:
            return "N/A"
        row = db.session.execute(
            text("SELECT name FROM users WHERE id = :id"),
            {"id": user_id}
        ).fetchone()
        return row[0] if row else "N/A"

    @staticmethod
    def get_products_map(product_ids):
        if not product_ids:
            return {}
        products = db.session.query(Product).filter(Product.id.in_(product_ids)).all()
        return {p.id: p for p in products}

    @staticmethod
    def get_active_waste_types(is_central=False):
        query = db.session.query(WasteType).filter(WasteType.is_active == True)
        if not is_central:
            return query.all()
        return query.filter(WasteType.applies_central == True).all()

    @staticmethod
    def get_lots_for_product(location_id, product_id):
        try:
            from app.waste.services.register_waste_service import get_product_lots
            lots = get_product_lots(location_id, product_id)
            if lots:
                formatted = []
                for l in lots:
                    if isinstance(l, dict):
                        lot_num = l.get("lot_number") or l.get("lot")
                        stock_val = l.get("stock_en_lote") if l.get("stock_en_lote") is not None else (l.get("current_quantity") or l.get("quantity") or 0.0)
                        formatted.append({
                            "lot_number": lot_num,
                            "expiration_date": str(l.get("expiration_date") or ""),
                            "stock": float(stock_val)
                        })
                if formatted:
                    return formatted
        except Exception:
            pass

        inv_row = db.session.query(Inventory).filter(
            Inventory.location_id == location_id,
            Inventory.product_id == product_id
        ).first()
        current_inv_stock = float(inv_row.current_quantity) if inv_row else 0.0

        rows = db.session.execute(
            text("""
                SELECT pd.lot_number, pd.expiration_date, pd.quantity
                FROM purchase_details pd
                WHERE pd.product_id = :pid AND pd.lot_number IS NOT NULL
                UNION
                SELECT md.lot_number, md.expiration_date, md.received_quantity
                FROM movement_details md
                WHERE md.product_id = :pid AND md.lot_number IS NOT NULL
            """),
            {"pid": product_id}
        ).fetchall()

        result = []
        for r in rows:
            exp_str = ""
            if r[1]:
                exp_str = r[1].strftime("%Y-%m-%d") if hasattr(r[1], "strftime") else str(r[1])
            max_possible = min(current_inv_stock, float(r[2] or 0.0))
            result.append({
                "lot_number": r[0],
                "expiration_date": exp_str,
                "stock": max_possible if max_possible > 0 else current_inv_stock
            })
        return result

    @staticmethod
    def get_waste_for_update(waste_id):
        return (
            db.session.query(Waste)
            .filter(Waste.id == waste_id)
            .with_for_update()
            .first()
        )

    @staticmethod
    def save_pending_edit(waste, clean_data, user_id):
        before_state = {
            "waste_type_id": waste.waste_type_id,
            "notes": waste.notes,
            "total_quantity": float(waste.total_quantity),
            "lines": [
                {
                    "product_id": d.product_id,
                    "lot_number": d.lot_number,
                    "quantity": float(d.quantity)
                }
                for d in waste.details
            ]
        }

        waste.waste_type_id = clean_data["waste_type_id"]
        waste.notes = clean_data["notes"]

        waste.details.clear()
        db.session.flush()

        total_qty = Decimal("0.00")
        total_cost = Decimal("0.00")

        for line in clean_data["lines"]:
            detail = WasteDetail(
                waste_id=waste.id,
                product_id=line["product_id"],
                lot_number=line["lot_number"],
                expiration_date=line["expiration_date"],
                quantity=line["quantity"],
                unit_cost=line["unit_cost"],
                subtotal_cost=line["subtotal_cost"]
            )
            db.session.add(detail)
            total_qty += line["quantity"]
            total_cost += line["subtotal_cost"]

        waste.total_quantity = total_qty
        waste.total_cost = total_cost

        after_state = {
            "waste_type_id": waste.waste_type_id,
            "notes": waste.notes,
            "total_quantity": float(waste.total_quantity),
            "lines": [
                {
                    "product_id": line["product_id"],
                    "lot_number": line["lot_number"],
                    "quantity": float(line["quantity"])
                }
                for line in clean_data["lines"]
            ]
        }

        audit = AuditLog(
            affected_table="waste",
            action="MERMA",
            severity="NORMAL",
            user_id=user_id,
            location_id=waste.location_id,
            timestamp=current_ve_time(),
            changed_data={
                "event": "MERMA_EDITADA",
                "waste_id": waste.id,
                "before": before_state,
                "after": after_state
            }
        )
        db.session.add(audit)
        db.session.commit()
        return waste

    @staticmethod
    def execute_reversion(waste_id, user_id, reason):
        waste = (
            db.session.query(Waste)
            .filter(Waste.id == waste_id)
            .with_for_update()
            .first()
        )

        stock_restorations = []
        for detail in waste.details:
            inv = (
                db.session.query(Inventory)
                .filter(
                    Inventory.location_id == waste.location_id,
                    Inventory.product_id == detail.product_id
                )
                .with_for_update()
                .first()
            )

            stock_before = float(inv.current_quantity) if inv else 0.0
            if inv:
                inv.current_quantity += detail.quantity
                stock_after = float(inv.current_quantity)
            else:
                inv = Inventory(
                    location_id=waste.location_id,
                    product_id=detail.product_id,
                    current_quantity=detail.quantity,
                    transit_quantity=Decimal("0.00"),
                    min_stock=Decimal("0.00")
                )
                db.session.add(inv)
                stock_after = float(detail.quantity)

            stock_restorations.append({
                "product_id": detail.product_id,
                "lot_number": detail.lot_number,
                "restored_qty": float(detail.quantity),
                "stock_before": stock_before,
                "stock_after": stock_after
            })

        waste.status = "REVERTIDO"
        waste.reverted_by_id = user_id
        waste.reverted_at = current_ve_time()
        waste.reversal_reason = reason

        audit = AuditLog(
            affected_table="waste",
            action="MERMA",
            severity="CRITICO",
            user_id=user_id,
            location_id=waste.location_id,
            timestamp=current_ve_time(),
            changed_data={
                "event": "MERMA_REVERTIDA",
                "waste_id": waste.id,
                "reverted_by_id": user_id,
                "reversal_reason": reason,
                "total_quantity": float(waste.total_quantity),
                "stock_restorations": stock_restorations
            }
        )
        db.session.add(audit)
        db.session.commit()
        return waste