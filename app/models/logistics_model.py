from app.extensions import db
from datetime import datetime

class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    inventories = db.relationship('Inventory', backref='location', lazy=True)

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    tax_id = db.Column(db.String(20), unique=True, nullable=False)
    contact_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))

class Purchase(db.Model):
    __tablename__ = 'purchases'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Numeric(15, 2))
    currency = db.Column(db.String(5))
    # Respaldo obligatorio de foto de factura
    invoice_url = db.Column(db.Text, nullable=False) 
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

class Movement(db.Model):
    __tablename__ = 'movements'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)
    origin_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    destination_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id')) # Quien envía
    
    # Soporte para confirmar, rechazar o mantener el traslado pendiente
    status = db.Column(db.String(20), default='PENDIENTE') # PENDIENTE, CONFIRMADO, RECHAZADO
    received_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guide_url = db.Column(db.Text, nullable=True) # Foto opcional de la guía física
    
    details = db.relationship('MovementDetail', backref='movement', lazy=True)

class MovementDetail(db.Model):
    __tablename__ = 'movement_details'
    id = db.Column(db.Integer, primary_key=True)
    movement_id = db.Column(db.Integer, db.ForeignKey('movements.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)