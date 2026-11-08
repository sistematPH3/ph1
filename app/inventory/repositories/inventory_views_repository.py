from sqlalchemy import func
from app import db
from app.models import Inventory, Product, Location, user_locations

class InventoryViewRepository:
    
    @staticmethod
    def get_inventory_by_location(location_id, search_term=None):
        """
        Consulta el inventario filtrado por una sede específica (excluyendo stock en cero).
        """
        query = Inventory.query.join(Product).join(Location).filter(
            Inventory.location_id == location_id,
            # <--Inventory.current_quantity > 0  # <-- FILTRO AGREGADO
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
        Consulta todo el inventario (Vista global de Administrador, excluyendo stock en cero).
        """
        query = Inventory.query.join(Product).join(Location).filter(
           # <--Inventory.current_quantity > 0  # <-- FILTRO AGREGADO se puede eliminar, si se descomenta hara que la validacion "el producto esta agotado" no funcione
        )
        
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

    @staticmethod
    def get_low_stock_counts_by_location():
        """
        Obtiene el desglose de alertas de stock bajo agrupado por sede activa.
        """
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