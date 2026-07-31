from app.models import Inventory, Product, Location, user_locations

class InventoryViewRepository:
    
    @staticmethod
    def get_inventory_by_location(location_id, search_term=None):
        """
        Consulta el inventario filtrado por una sede específica.
        """
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
        """
        Consulta todo el inventario (Vista global de Administrador).
        """
        query = Inventory.query.join(Product).join(Location)
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_user_assigned_locations(user_id):
        """
        Obtiene las sedes asociadas al usuario haciendo JOIN con la tabla user_locations.
        """
        return Location.query.join(
            user_locations, 
            Location.id == user_locations.c.location_id
        ).filter(user_locations.c.user_id == user_id).all()

    @staticmethod
    def get_all_active_locations():
        """
        Obtiene todas las sedes activas para el selector del Administrador.
        """
        return Location.query.filter_by(is_active=True).all()