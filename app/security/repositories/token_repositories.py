from datetime import datetime
from werkzeug.security import generate_password_hash  # <-- NUEVA IMPORTACIÓN
from app.extensions import db  
from app.models.security_model import User, PasswordRecovery 

def guardar_token(email, token, expiracion):
    """Guarda el token relacionándolo con el ID del usuario en la nueva tabla."""
    try:
        usuario = User.query.filter_by(email=email).first()
        if not usuario:
            return False 

        nueva_recuperacion = PasswordRecovery(
            user_id=usuario.id,
            token=token,
            created_at=datetime.now(),
            expires_at=expiracion
        )
        
        db.session.add(nueva_recuperacion)
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback() 
        print(f"Error en BD al guardar token: {e}")
        return False

def actualizar_password_con_token(token, nueva_password):
    """Valida el token en la nueva tabla y actualiza la contraseña del usuario."""
    try:
        recuperacion = PasswordRecovery.query.filter(
            PasswordRecovery.token == token,
            PasswordRecovery.expires_at > datetime.now()
        ).first()
        
        if not recuperacion:
            return False 
            
        usuario = User.query.get(recuperacion.user_id)
        if not usuario:
            return False
            
        usuario.password_hash = generate_password_hash(nueva_password) 
        
        db.session.delete(recuperacion)
        db.session.commit()
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"Error al procesar el cambio de contraseña: {e}")
        return False

def consultar_vigencia_token(token):
    """Consulta en la base de datos si el token existe y si aún no ha expirado."""
    try:
        recuperacion = PasswordRecovery.query.filter(
            PasswordRecovery.token == token,
            PasswordRecovery.expires_at > datetime.now()
        ).first()
        
        
        return recuperacion is not None
        
    except Exception as e:
        print(f"Error al consultar vigencia del token: {e}")
        return False