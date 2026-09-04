from app.extensions import db
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

class WasteType(db.Model):
    __tablename__ = 'waste_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # Ej: Vencido, Dañado, Robo
    # Nuevos campos del catálogo de tipos de merma
    code = db.Column(db.String(40), unique=True)  # Ej: VENCIDO, TEMPERATURA, ROBO_SOSPECHA
    description = db.Column(db.Text)
    severity = db.Column(db.String(15), nullable=False, default='MEDIA')  # MEDIA, ALTA, CRITICA
    requires_approval = db.Column(db.Boolean, nullable=False, default=False)  # TEMPERATURA/ROBO_SOSPECHA siempre
    applies_central = db.Column(db.Boolean, nullable=False, default=False)  # ¿Aplica a Sede Central (sin cocina)?
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    wastes = db.relationship('Waste', backref='waste_type', lazy=True)


class Waste(db.Model):
    __tablename__ = 'waste'
    __table_args__ = (
        db.Index('idx_waste_location_date', 'location_id', sa.text('date DESC')),
        db.Index('idx_waste_status', 'status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    # Cabecera de la merma (Maestro-Detalle: un ticket con varias líneas)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    waste_type_id = db.Column(db.Integer, db.ForeignKey('waste_types.id'))
    evidence_url = db.Column(db.Text) # Foto de la merma (siempre opcional)
    notes = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id')) # Autor (se conserva)

    # Estado del flujo de aprobación
    status = db.Column(db.String(20), nullable=False, default='APROBADO')  # PENDIENTE/APROBADO/RECHAZADO/REVERTIDO
    total_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_cost = db.Column(db.Numeric(15, 2), nullable=False, default=0)  # Costo interno (solo M9)
    currency = db.Column(db.String(5), nullable=False, default='USD')

    # Aprobación (solo Admin)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)

    # Reversión lógica (solo Admin, motivo obligatorio)
    reverted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reverted_at = db.Column(db.DateTime)
    reversal_reason = db.Column(db.Text)

    # Cancelación por el autor (merma PENDIENTE retirada antes de la respuesta)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.Text)

    # Líneas (multi-lote) de la merma
    details = db.relationship('WasteDetail', backref='waste', lazy=True,
                              cascade='all, delete-orphan')


class WasteDetail(db.Model):
    """Línea de una merma (producto + lote + vencimiento + cantidad + costo interno)."""
    __tablename__ = 'waste_details'
    __table_args__ = (
        db.Index('idx_waste_details_waste_id', 'waste_id'),
        db.Index('idx_waste_details_product_lot', 'product_id', 'lot_number'),
    )
    id = db.Column(db.Integer, primary_key=True)
    waste_id = db.Column(db.Integer, db.ForeignKey('waste.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    lot_number = db.Column(db.String(50), nullable=False)
    expiration_date = db.Column(db.Date)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(15, 4), nullable=False, default=0)  # Costo interno (M9)
    subtotal_cost = db.Column(db.Numeric(15, 2), nullable=False, default=0)


class AppParameter(db.Model):
    """Pizarra de reglas (app_parameters). Solo reglas de TIEMPO del control de mermas."""
    __tablename__ = 'app_parameters'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)

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