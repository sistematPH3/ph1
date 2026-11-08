from app.extensions import db
from flask_login import UserMixin
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import validates
from sqlalchemy.dialects.postgresql import JSONB

# ⚠️ SE ELIMINÓ EL IMPORT GLOBAL DE AUDIT_VALIDATORS PARA EVITAR LA IMPORTACIÓN CIRCULAR

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


    # =========================================================================
    # --- LÓGICA DE SEGURIDAD Y ROLES DE LA BASE DE DATOS ---
    # =========================================================================

    @property
    def is_admin(self):
        return self.role is not None and self.role.name == 'Administrator'

    @property
    def is_manager(self):
        return self.role is not None and self.role.name == 'Manager'

    @property
    def is_assistant_manager(self):
        return self.role is not None and self.role.name == 'Assistant Manager'

    @property
    def is_operations(self):
        return self.role is not None and self.role.name == 'Operations'

    @property
    def is_management(self):
        return self.role is not None and self.role.name == 'Management'
    
    @property
    def is_finance(self):
        return self.role is not None and self.role.name == 'Finance'
    
    @property
    def is_guest(self):
        # Reconocimiento robusto de usuarios invitados por ID o por nombre string
        return self.role_id == 0 or (self.role is not None and self.role.name == 'Guest')
    
    @property
    def is_fully_active(self):
        """
        Validación de habilitación de usuario:
        1. Estado de actividad general (is_active).
        2. Asignación obligatoria de un rol.
        3. Vinculación a sedes activas (Excluye administradores e invitados).
        """
        if not self.is_active:
            return False
        
        # Validación de rol
        if self.role is None:
            return False
        
        # Validación de sedes (Omitida para administradores e invitados)
        if not self.is_admin and not self.is_guest:
            active_assigned = any(loc.is_active for loc in self.locations)
            if not active_assigned:
                return False
        
        return True

# --- SINCRONIZACIÓN DE ESTADO SEGURA ---
    def sync_activation_status(self):
        """
        Ajusta is_active solo si el usuario viola la regla de sedes.
        Si el administrador desactivó manualmente a un usuario con sedes, 
        esta lógica NO lo reactivará automáticamente.
        """
        # Excepción absoluta para roles especiales
        if self.is_admin or self.is_guest:
            if not self.is_active:
                self.is_active = True
                db.session.commit()
            return
        
        # Obtenemos sedes activas
        active_assigned_locations = [loc for loc in self.locations if loc.is_active]
        
        # REGLA: Si NO tiene sedes o NO tiene ninguna activa, DEBE estar desactivado.
        if len(self.locations) == 0 or len(active_assigned_locations) == 0:
            if self.is_active: # Solo cambiamos si realmente estaba activo
                self.is_active = False
                db.session.commit()

    def __repr__(self):
        return f'<User {self.email}>'

class Notification(db.Model):
    """
    Representa la bandeja interna. Se filtra por sede y el Administrador la visualiza toda.

    Desde la mejora de la bandeja de respuestas, se usa también para avisar a
    los receptores de traslados cuando el Administrador emitió un dictamen
    (movement_id apunta al traslado y type es 'RESPUESTA_TRASLADO'). El
    estado de "leído" vive aquí (is_read), no en el navegador.
    """
    __tablename__ = 'notifications'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'movement_id', 'type',
                            name='uq_notif_user_movement_type'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True) 
    type = db.Column(db.String(30)) # Ej. 'ALERTA_STOCK', 'TRASLADO_PENDIENTE'
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    movement_id = db.Column(db.Integer, nullable=True)  # Traslado de la respuesta (RESPUESTA_TRASLADO)
    waste_id = db.Column(db.Integer, nullable=True)  # Merma de la decisión (MERMA_APROBADA / MERMA_RECHAZADA)
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

class LoginAudit(db.Model): 
    __tablename__ = 'login_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    
    action = db.Column(db.String(50), nullable=False) # 'INICIO_SESION', 'CERRAR_SESION', 'CAMBIO_CONTRASENA'
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone(timedelta(hours=-4))).replace(tzinfo=None))
    
    user = db.relationship('User', backref=db.backref('login_logs', lazy=True))
    location = db.relationship('Location', backref=db.backref('login_logs', lazy=True))
    role = db.relationship('Role', backref=db.backref('login_logs', lazy=True))

    # --- DECORADORES DE VALIDACIÓN (CON IMPORTS LOCALES) ---

    @validates('user_id')
    def validate_user(self, key, value):
        from app.security.requests.audit_validators import validar_id_entidad
        return validar_id_entidad('user_id', value, obligatorio=True)

    @validates('role_id')
    def validate_role(self, key, value):
        from app.security.requests.audit_validators import validar_id_entidad
        return validar_id_entidad('role_id', value, obligatorio=True)

    @validates('location_id')
    def validate_location(self, key, value):
        from app.security.requests.audit_validators import validar_id_entidad
        return validar_id_entidad('location_id', value, obligatorio=False)

    @validates('action')
    def validate_action(self, key, value):
        from app.security.requests.audit_validators import validar_accion_auditoria
        return validar_accion_auditoria(value)

    @validates('timestamp')
    def validate_timestamp(self, key, value):
        from app.security.requests.audit_validators import validar_timestamp_auditoria
        return validar_timestamp_auditoria(value)

    def __repr__(self):
        return f'<LoginAudit {self.action} - User ID: {self.user_id} - Role ID: {self.role_id} at {self.timestamp}>'

class UserAudit(db.Model):
    __tablename__ = 'user_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    changed_data = db.Column(JSONB)

    responsible_user = db.relationship('User', foreign_keys=[responsible_user_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    role = db.relationship('Role')

    @validates('responsible_user_id', 'target_user_id', 'role_id')
    def validate_ids(self, key, value):
        from app.security.requests.audit_validators import validar_id_entidad
        obligatorio = False if key == 'location_id' else True
        return validar_id_entidad(key, value, obligatorio=obligatorio)

    @validates('action')
    def validate_action(self, key, value):
        from app.security.requests.audit_validators import validar_accion_auditoria
        return validar_accion_auditoria(value)

    @validates('timestamp')
    def validate_timestamp(self, key, value):
        from app.security.requests.audit_validators import validar_timestamp_auditoria
        return validar_timestamp_auditoria(value)