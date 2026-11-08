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
        return Product.query.get(product_id)

    @staticmethod
    def find_by_sku(sku):
        return Product.query.filter_by(sku=sku).first()

    @staticmethod
    def save(product):
        db.session.add(product)
        db.session.commit()
        return product