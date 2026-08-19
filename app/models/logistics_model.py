from app.extensions import db
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.postgresql import JSONB

class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    detailed_address = db.Column(db.Text)
    state = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    
    inventories = db.relationship('Inventory', backref='location', lazy=True)
    
    @hybrid_property
    def address(self):
        if self.detailed_address:
            return f"{self.state} - {self.detailed_address}"
        return self.state

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    tax_id = db.Column(db.String(20), unique=True, nullable=False)
    contact_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100)) 
    status = db.Column(db.String(20), default='ACTIVO')

class ExchangeRateHistory(db.Model):
    __tablename__ = 'exchange_rate_history'
    id = db.Column(db.Integer, primary_key=True)
    currency = db.Column(db.String(5), nullable=False)
    rate = db.Column(db.Numeric(15, 4), nullable=False)
    source = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

class Purchase(db.Model):
    __tablename__ = 'purchases'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'))
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Numeric(15, 2)) 
    currency = db.Column(db.String(5))
    exchange_rate = db.Column(db.Numeric(15, 4)) 
    invoice_url = db.Column(db.Text, nullable=False) 
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(20), default='COMPLETED', nullable=False)
    
    details = db.relationship('PurchaseDetail', backref='purchase', lazy=True)

class PurchaseDetail(db.Model):
    __tablename__ = 'purchase_details'
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    lot_number = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    foreign_price = db.Column(db.Numeric(15, 2)) 
    price_bs = db.Column(db.Numeric(15, 2))
    expiration_date = db.Column(db.Date, nullable=True)
    
class Movement(db.Model):
    __tablename__ = 'movements'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)
    origin_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    destination_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(30), default='EN_TRANSITO', nullable=False)
    received_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolution_notes = db.Column(db.Text, nullable=True)
    
    details = db.relationship('MovementDetail', backref='movement', lazy=True)

class MovementDetail(db.Model):
    __tablename__ = 'movement_details'
    id = db.Column(db.Integer, primary_key=True)
    movement_id = db.Column(db.Integer, db.ForeignKey('movements.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    lot_number = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    received_quantity = db.Column(db.Numeric(10, 2), nullable=True, default=None)
    missing_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    expiration_date = db.Column(db.Date, nullable=True)

class PurchaseAuditLog(db.Model):
    __tablename__ = 'purchase_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchases.id'), nullable=False)
    action_type = db.Column(db.String(20), nullable=False)
    previous_data = db.Column(JSONB, nullable=False)
    new_data = db.Column(JSONB, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)