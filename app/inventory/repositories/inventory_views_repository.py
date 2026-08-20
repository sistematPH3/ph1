from sqlalchemy import func
from app import db
from app.models import Inventory, Product, Location, user_locations
from app.models.logistics_model import Purchase, PurchaseDetail, Movement, MovementDetail

class InventoryViewRepository:
    
    @staticmethod
    def get_inventory_by_location(location_id, search_term=None):
        query = Inventory.query.join(Product).join(Location).filter(
            Inventory.location_id == location_id
        )
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_all_inventory(search_term=None):
        query = Inventory.query.join(Product).join(Location)
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_user_assigned_locations(user_id):
        return Location.query.join(
            user_locations, 
            Location.id == user_locations.c.location_id
        ).filter(user_locations.c.user_id == user_id).all()

    @staticmethod
    def get_all_active_locations():
        return Location.query.filter_by(is_active=True).all()

    @staticmethod
    def get_low_stock_counts_by_location():
        results = db.session.query(
            Location.id,
            Location.name,
            func.count(Inventory.id).label('low_stock_count')
        ).join(Inventory, Location.id == Inventory.location_id)\
         .filter(
            Location.is_active == True,
            Inventory.current_quantity > 0,
            Inventory.current_quantity <= Inventory.min_stock
        ).group_by(Location.id, Location.name).all()

        return [
            {
                'location_id': r.id,
                'location_name': r.name,
                'count': r.low_stock_count
            } for r in results if r.low_stock_count > 0
        ]

    @staticmethod
    def get_product_lots_by_location(location_id, product_id):
        if int(location_id) == 1:
            records = db.session.query(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date,
                func.sum(PurchaseDetail.quantity).label('total_qty')
            ).join(
                Purchase, PurchaseDetail.purchase_id == Purchase.id
            ).filter(
                Purchase.status == 'COMPLETED',
                PurchaseDetail.product_id == product_id,
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).group_by(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date
            ).order_by(
                PurchaseDetail.expiration_date.asc().nullslast()
            ).all()
        else:
            records = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date,
                func.sum(func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity)).label('total_qty')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.status == 'COMPLETED',
                Movement.destination_location_id == location_id,
                MovementDetail.product_id == product_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).order_by(
                MovementDetail.expiration_date.asc().nullslast()
            ).all()

        lots = []
        for r in records:
            lots.append({
                'lot_number': r.lot_number,
                'expiration_date': r.expiration_date.strftime('%d/%m/%Y') if r.expiration_date else 'Sin vencimiento',
                'quantity': float(r.total_qty) if r.total_qty is not None else 0.0
            })
        return lots