from app.extensions import db

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    unit_of_measure = db.Column(db.String(20))
    minimum_stock = db.Column(db.Numeric(10, 2), default=20.00)
    next_expiration_date = db.Column(db.Date)
    inventories = db.relationship('Inventory', backref='product', lazy=True)

class Inventory(db.Model):
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    current_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)