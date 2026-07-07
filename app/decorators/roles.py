from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

def management_required(f):
    """Decorador para proteger rutas exclusivas de Dirección"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Verifica si el usuario está autenticado y si tiene el rol de management
        if not current_user.is_authenticated or not current_user.is_management:
            flash("Acceso denegado: Se requieren privilegios de Dirección.", "danger")
            return redirect(url_for('security.login'))
        
        # 2. Si todo está bien, ejecuta la función original
        return f(*args, **kwargs)
    
    return decorated_function