from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location
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
    def update_stock(inventory_item, quantity):
        inventory_item.current_quantity -= quantity
        db.session.commit()
        return inventory_item