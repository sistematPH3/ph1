from app.extensions import db

class Category(db.Model):
    """
    Categorías Macro (Contables y de Reportes Financieros)
    """
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    
    # Relación: Una categoría macro agrupa muchos tipos de productos operativos
    product_types = db.relationship('ProductType', backref='category', lazy=True)


class ProductType(db.Model):
    """
    Centraliza las reglas operativas de la franquicia.
    Aquí se decide si el vencimiento es manual o automático por días.
    """
    __tablename__ = 'product_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    
    # Reglas de negocio para las fechas de vencimiento
    requires_manual_date = db.Column(db.Boolean, default=False, nullable=False)
    shelf_life_days = db.Column(db.Integer, nullable=True) # NULL si requiere fecha de fábrica

    # Estatus operativo de la categoría
    is_active = db.Column(db.Boolean, default=True, nullable=False, server_default='true')

    # Relación: Un tipo de producto operativo agrupa muchos insumos/productos reales
    products = db.relationship('Product', backref='product_type', lazy=True)


class Product(db.Model):
    """
    El insumo físico real de la franquicia.
    """
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    
    # RELACIÓN ÚNICA: Conectado al Tipo Operativo para heredar sus reglas
    product_type_id = db.Column(db.Integer, db.ForeignKey('product_types.id'), nullable=True)
    
    unit_of_measure = db.Column(db.String(20))
    technical_description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    inventories = db.relationship('Inventory', backref='product', lazy=True)


class Inventory(db.Model):
    """
    Inventario físico por sede (específico).
    """
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    
    # Manejo de cantidades y alertas
    current_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    # CAMPO AÑADIDO: Saldo retenido en tránsito para custodias físicas
    transit_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    # CAMPO AÑADIDO: Necesario para que el trigger sepa cuándo lanzar la alerta
    min_stock = db.Column(db.Numeric(10, 2), nullable=False, default=20.00)