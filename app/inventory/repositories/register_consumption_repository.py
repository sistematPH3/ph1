import json
from datetime import datetime
from sqlalchemy import func
from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import AuditLog
from app.models.security_model import User, user_locations

class RegisterConsumptionRepository:
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_all_sedes():
        return Location.query.filter(Location.is_active == True, Location.id != 1).all()

    @staticmethod
    def is_valid_sede(location_id):
        return Location.query.filter(Location.id == location_id, Location.is_active == True, Location.id != 1).first() is not None

    @staticmethod
    def get_user_locations(user_id):
        loc_ids_result = db.session.query(user_locations.c.location_id).filter(user_locations.c.user_id == user_id).all()
        loc_ids = [row[0] for row in loc_ids_result]
        
        if not loc_ids:
            return []
            
        return Location.query.filter(Location.id.in_(loc_ids), Location.is_active == True, Location.id != 1).all()

    @staticmethod
    def get_products_in_inventory(location_id):
        return db.session.query(Product).join(
            Inventory, Product.id == Inventory.product_id
        ).filter(
            Inventory.location_id == location_id,
            Inventory.current_quantity > 0,
            Product.is_active == True
        ).all()

    @staticmethod
    def get_inventory_item(product_id, location_id):
        return Inventory.query.filter_by(
            product_id=product_id,
            location_id=location_id
        ).first()

    @staticmethod
    def get_product_lots(product_id, location_id):
        loc_id = int(location_id)
        prod_id = int(product_id)

        entradas_por_lote = {}
        salidas_traslados = {}

        if loc_id == 1:
            purchase_records = db.session.query(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date,
                func.sum(PurchaseDetail.quantity).label('total_qty')
            ).join(
                Purchase, PurchaseDetail.purchase_id == Purchase.id
            ).filter(
                func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
                PurchaseDetail.product_id == prod_id,
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).group_by(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date
            ).all()

            for r in purchase_records:
                lot = r.lot_number.strip()
                entradas_por_lote[lot] = {
                    'expiration_date': r.expiration_date,
                    'total_in': float(r.total_qty or 0.0)
                }

            movements_out = db.session.query(
                MovementDetail.lot_number,
                func.sum(MovementDetail.quantity).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == 1,
                Movement.status.notin_(['ANULADO', 'CANCELADO', 'RECHAZADO', 'CANCELADO_EMISOR']),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None)
            ).group_by(MovementDetail.lot_number).all()

            salidas_traslados = {r.lot_number.strip(): float(r.total_out or 0.0) for r in movements_out if r.lot_number}

        else:
            valid_statuses = ['COMPLETED', 'COMPLETADO', 'NOVEDAD_FALTANTE', 'CERRADO_POR_ADMIN', 'CERRADO_CON_PERDIDA']
            movement_records = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date,
                func.sum(func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity)).label('total_qty')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                func.upper(Movement.status).in_(valid_statuses),
                Movement.destination_location_id == loc_id,
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).all()

            for r in movement_records:
                lot = r.lot_number.strip()
                entradas_por_lote[lot] = {
                    'expiration_date': r.expiration_date,
                    'total_in': float(r.total_qty or 0.0)
                }

        audit_records = db.session.query(
            AuditLog.changed_data
        ).filter(
            AuditLog.location_id == loc_id,
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA', 'MERMA'])
        ).all()

        salidas_consumo = {}
        for (c_data,) in audit_records:
            if not c_data:
                continue
            if isinstance(c_data, str):
                try:
                    c_data = json.loads(c_data)
                except Exception:
                    continue
            if not isinstance(c_data, dict):
                continue
                
            p_id = c_data.get('product_id')
            l_num = c_data.get('lot_number')
            try:
                qty_change = float(c_data.get('quantity_changed', 0.0))
            except (TypeError, ValueError):
                qty_change = 0.0

            matches_product = False
            if p_id is not None:
                try:
                    matches_product = int(p_id) == prod_id
                except (TypeError, ValueError):
                    matches_product = False

            if matches_product and l_num and l_num != 'N/A':
                l_num_clean = str(l_num).strip()
                salidas_consumo[l_num_clean] = salidas_consumo.get(l_num_clean, 0.0) + abs(qty_change)

        lots = []
        for lot_num, data in entradas_por_lote.items():
            total_in = data['total_in']
            total_out_traslados = salidas_traslados.get(lot_num, 0.0)
            total_out_consumos = salidas_consumo.get(lot_num, 0.0)
            
            disponible = total_in - total_out_traslados - total_out_consumos
            
            if disponible > 0.001:
                lots.append({
                    'lot_number': lot_num,
                    'expiration_date': data['expiration_date'].strftime('%d/%m/%Y') if data['expiration_date'] else 'Sin vencimiento',
                    'exp_date_raw': data['expiration_date'],
                    'quantity': round(float(disponible), 2)
                })

        lots.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))
        
        for l in lots:
            l.pop('exp_date_raw', None)
            
        return lots

    @staticmethod
    def record_lot_consumption_audit(inventory_item, lot_number, quantity_consumed, previous_stock, new_stock, user_id=None, notes=None):
        min_stock = float(getattr(inventory_item, 'min_stock', 20))
        if new_stock <= 0:
            severidad = 'CRITICO'
        elif new_stock <= min_stock:
            severidad = 'ALERTA'
        else:
            severidad = 'NORMAL'

        product_name = inventory_item.product.name if hasattr(inventory_item, 'product') and inventory_item.product else f"Insumo #{inventory_item.product_id}"

        note_text = notes or "Registro de consumo de cocina"
        if lot_number and lot_number != 'N/A':
            note_text = f"{note_text} (Lote: {lot_number})"

        changed_data = json.dumps({
            'product_id': inventory_item.product_id,
            'product_name': product_name,
            'lot_number': lot_number or 'N/A',
            'previous_quantity': float(previous_stock),
            'new_quantity': float(new_stock),
            'quantity_changed': -abs(float(quantity_consumed)),
            'notes': note_text
        })

        try:
            user_id_final = int(user_id) if user_id is not None else 1
        except (ValueError, TypeError):
            user_id_final = 1

        audit_entry = AuditLog(
            user_id=user_id_final,
            location_id=inventory_item.location_id,
            action='GASTO_COCINA',
            severity=severidad,
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)