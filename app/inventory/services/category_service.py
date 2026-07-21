from app import db
from app.models.inventory_model import ProductType, Category

class CategoryService:

    @staticmethod
    def get_all_product_types():
        return ProductType.query.order_by(ProductType.name).all()

    @staticmethod
    def get_product_type_by_id(type_id):
        return ProductType.query.get_or_404(type_id)

    @staticmethod
    def create_category(form_data):
        name = form_data.get('name')
        shelf_life_days = form_data.get('shelf_life_days', 0)
        requires_manual_date = bool(form_data.get('requires_manual_date'))

        try:
            shelf_life_days = int(shelf_life_days) if shelf_life_days else None
        except ValueError:
            shelf_life_days = None

        category = Category.query.filter_by(name=name).first()
        
        if not category:
            category = Category(name=name)
            db.session.add(category)
            db.session.commit()

        new_type = ProductType(
            name=name,
            category_id=category.id,
            requires_manual_date=requires_manual_date,
            shelf_life_days=shelf_life_days if not requires_manual_date else None
        )
        
        db.session.add(new_type)
        db.session.commit()
        return new_type

    @staticmethod
    def update_category(type_id, form_data):
        product_type = ProductType.query.get_or_404(type_id)
        
        new_name = form_data.get('name')
        product_type.requires_manual_date = bool(form_data.get('requires_manual_date'))
        
        shelf_life_days = form_data.get('shelf_life_days', 0)
        try:
            product_type.shelf_life_days = int(shelf_life_days) if shelf_life_days else None
        except ValueError:
            product_type.shelf_life_days = None

        if product_type.category_id:
            category = Category.query.get(product_type.category_id)
            if category:
                category.name = new_name
        
        product_type.name = new_name
        db.session.commit()
        return product_type