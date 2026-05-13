from app.extensions import db
from flask_login import UserMixin
from datetime import datetime

# Tabla intermedia para la asignación de múltiples sedes a usuarios
user_locations = db.Table('user_locations',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('location_id', db.Integer, db.ForeignKey('locations.id'), primary_key=True)
)

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # Admin, Finanzas, Operaciones, etc.
    users = db.relationship('User', backref='role', lazy=True)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), default=0)
    is_active = db.Column(db.Boolean, default=True)

    # Relación muchos a muchos con sedes/locales
    locations = db.relationship('Location', secondary=user_locations, 
                                backref=db.backref('assigned_users', lazy='dynamic'))
    
    # Buzón interno / Bandeja de alarmas
    notifications = db.relationship('Notification', backref='recipient', lazy=True)

    def __repr__(self):
        return f'<User {self.email}>'

class Notification(db.Model):
    """
    Representa la bandeja interna. Se filtra por sede y el Administrador la visualiza toda.
    """
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True) 
    type = db.Column(db.String(30)) # Ej. 'ALERTA_STOCK', 'TRASLADO_PENDIENTE'
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PasswordRecovery(db.Model):
    """
    Manejo de recuperación de contraseña de un solo uso (resiliente).
    """
    __tablename__ = 'password_recoveries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False) 

    user = db.relationship('User', backref=db.backref('password_recoveries', lazy=True))

    def __repr__(self):
        return f'<PasswordRecovery Token: {self.token}>'