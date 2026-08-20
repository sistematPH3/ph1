import json
from datetime import datetime
from sqlalchemy import text
from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.security_model import User, user_locations

class RegisterConsumptionRepository:
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_all_sedes():
        return Location.query.filter(Location.is_active == True, Location.id != 1).all()

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
        if int(location_id) == 1:
            records = db.session.query(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date
            ).join(
                Purchase, PurchaseDetail.purchase_id == Purchase.id
            ).filter(
                Purchase.status == 'COMPLETED',
                PurchaseDetail.product_id == product_id,
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).distinct().order_by(
                PurchaseDetail.expiration_date.asc().nullslast()
            ).all()
        else:
            records = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.status == 'COMPLETED',
                Movement.destination_location_id == location_id,
                MovementDetail.product_id == product_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).distinct().order_by(
                MovementDetail.expiration_date.asc().nullslast()
            ).all()

        lots = []
        for r in records:
            lots.append({
                'lot_number': r.lot_number,
                'expiration_date': r.expiration_date.strftime('%d/%m/%Y') if r.expiration_date else 'Sin vencimiento'
            })
        return lots

    @staticmethod
    def update_stock(inventory_item, quantity, user_id=None, notes=None, lot_number=None):
        stock_anterior = float(inventory_item.current_quantity)
        nuevo_stock = stock_anterior - float(quantity)
        inventory_item.current_quantity = nuevo_stock

        min_stock = float(getattr(inventory_item, 'min_stock', 20))
        if nuevo_stock <= 0:
            severidad = 'CRITICO'
        elif nuevo_stock <= min_stock:
            severidad = 'ALERTA'
        else:
            severidad = 'NORMAL'

        product_name = inventory_item.product.name if hasattr(inventory_item, 'product') and inventory_item.product else f"Insumo #{inventory_item.product_id}"

        note_text = notes or "Registro de consumo de cocina"
        if lot_number:
            note_text = f"{note_text} (Lote: {lot_number})"

        changed_data = json.dumps({
            'product_name': product_name,
            'lot_number': lot_number or 'N/A',
            'previous_quantity': stock_anterior,
            'new_quantity': nuevo_stock,
            'quantity_changed': -abs(float(quantity)),
            'notes': note_text
        })

        try:
            user_id_final = int(user_id) if user_id is not None else 1
        except (ValueError, TypeError):
            user_id_final = 1

        audit_query = text("""
            INSERT INTO audit_logs (user_id, location_id, action, severity, timestamp, changed_data)
            VALUES (:user_id, :location_id, :action, :severity, :timestamp, :changed_data)
        """)

        db.session.execute(audit_query, {
            'user_id': user_id_final,
            'location_id': inventory_item.location_id,
            'action': 'GASTO_COCINA',
            'severity': severidad,
            'timestamp': datetime.now(),
            'changed_data': changed_data
        })

        return inventory_item