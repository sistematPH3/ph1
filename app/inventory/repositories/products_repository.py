from app.models.inventory_model import Product  # Tu modelo de datos modificado
from app import db

#archivo de diego

class ProductRepository:
    
    @staticmethod
    def get_all_active():
        """Cambiado para el listado general: recupera todos los productos para poder ver los inhabilitados"""
        return Product.query.all()

    @staticmethod
    def search_by_name_or_sku(search_query):
        """Busca coincidencias parciales en todos los registros de la base de datos"""
        wildcard = f"%{search_query}%"
        return Product.query.filter(
            (Product.name.ilike(wildcard)) | (Product.sku.ilike(wildcard))
        ).all()

    @staticmethod
    def find_by_id(product_id):
        """Busca un producto por su clave primaria ID."""
        return Product.query.get(product_id)

    @staticmethod
    def find_by_sku(sku):
        """Busca un producto por su SKU exacto (para control de unicidad)."""
        return Product.query.filter_by(sku=sku).first()

    @staticmethod
    def save(product):
        """Guarda un nuevo producto o persiste los cambios de uno editado."""
        db.session.add(product)
        db.session.commit()
        return product