from app.extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB

class WasteType(db.Model):
    __tablename__ = 'waste_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # Ej: Vencido, Dañado, Robo
    wastes = db.relationship('Waste', backref='waste_type', lazy=True)

class Waste(db.Model):
    __tablename__ = 'waste'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    waste_type_id = db.Column(db.Integer, db.ForeignKey('waste_types.id'))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    evidence_url = db.Column(db.Text) # Foto de la merma
    notes = db.Column(db.Text) 
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

class AuditLog(db.Model):
    """
    Este modelo es vital para tu control de seguridad. 
    Registra quién hizo qué y qué datos cambiaron exactamente.
    """
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    affected_table = db.Column(db.String(50))
    action = db.Column(db.String(50)) # INSERT, UPDATE, DELETE
    severity = db.Column(db.String(20), default='NORMAL') # NORMAL, ALERTA, CRITICO
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # NUEVO CAMPO: Relación explícita con la sede para la auditoría
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True)
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    changed_data = db.Column(JSONB) # Almacena el antes/después en formato JSON