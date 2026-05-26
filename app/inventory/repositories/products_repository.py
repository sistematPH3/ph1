from app.models.inventory_model import Product  # Tu modelo de datos modificado
from app import db

#archivo de diego

class ProductRepository:
    
    @staticmethod
    def get_all_active():
        """Recupera todos los productos que estén habilitados en el sistema."""
        return Product.query.filter_by(is_active=True).all()

    @staticmethod
    def search_by_name_or_sku(search_term):
        """
        Mecanismo de Consulta léxica (Búsqueda indexada).
        Busca coincidencias parciales ignorando mayúsculas/minúsculas.
        """
        wildcard = f"%{search_term}%"
        return Product.query.filter(
            Product.is_active == True,
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