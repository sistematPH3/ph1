from app import db
from app.models.inventory_model import ProductType, Category
from app.inventory.requests.categories_request import validate_expiration_control

class CategoryService:

    @staticmethod
    def get_all_product_types():
        return ProductType.query.order_by(ProductType.name).all()

    @staticmethod
    def get_product_type_by_id(type_id):
        return db.session.get(ProductType, type_id)

    @staticmethod
    def create_category(form_data):
        name = form_data.get('name')

        # La regla de vencimiento es obligatoria y exclusiva de la categoría.
        errors, requires_manual_date, shelf_life_days = validate_expiration_control(form_data)
        if errors:
            raise ValueError(next(iter(errors.values())))

        category = Category.query.filter_by(name=name).first()
        
        if not category:
            category = Category(name=name)
            db.session.add(category)
            db.session.commit()

        new_type = ProductType(
            name=name,
            category_id=category.id,
            requires_manual_date=requires_manual_date,
            shelf_life_days=shelf_life_days
        )
        
        db.session.add(new_type)
        db.session.commit()
        return new_type

    @staticmethod
    def update_category(type_id, form_data):
        product_type = ProductType.query.get_or_404(type_id)
        
        new_name = form_data.get('name')

        # La regla de vencimiento es obligatoria y exclusiva de la categoría.
        errors, requires_manual_date, shelf_life_days = validate_expiration_control(form_data)
        if errors:
            raise ValueError(next(iter(errors.values())))

        product_type.requires_manual_date = requires_manual_date
        product_type.shelf_life_days = shelf_life_days

        if product_type.category_id:
            category = db.session.get(Category, product_type.category_id)
            if category:
                category.name = new_name
        
        product_type.name = new_name
        db.session.commit()
        return product_type