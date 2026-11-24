from sqlalchemy import func
from app.models.inventory_model import Product  
from app import db

class ProductRepository:
    
    @staticmethod
    def get_all_active():
        return Product.query.all()

    @staticmethod
    def search_by_name_or_sku(search_query):
        wildcard = f"%{search_query}%"
        return Product.query.filter(
            (Product.name.ilike(wildcard)) | (Product.sku.ilike(wildcard))
        ).all()

    @staticmethod
    def find_by_id(product_id):
        return db.session.get(Product, product_id)

    @staticmethod
    def find_by_sku(sku):
        return Product.query.filter_by(sku=sku).first()

    @staticmethod
    def find_by_name(name):
        """Busca un insumo por nombre sin distinguir mayúsculas/minúsculas."""
        normalized = (name or '').strip().lower()
        if not normalized:
            return None
        return Product.query.filter(func.lower(Product.name) == normalized).first()

    @staticmethod
    def save(product):
        db.session.add(product)
        db.session.commit()
        return product