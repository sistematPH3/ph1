from app.extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB

class WasteType(db.Model):
    __tablename__ = 'waste_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

class Waste(db.Model):
    __tablename__ = 'waste'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    waste_type_id = db.Column(db.Integer, db.ForeignKey('waste_types.id'))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    evidence_url = db.Column(db.Text) # Evidencia digital (foto)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    affected_table = db.Column(db.String(50))
    action = db.Column(db.String(50))
    severity = db.Column(db.String(20), default='NORMAL')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    changed_data = db.Column(JSONB)