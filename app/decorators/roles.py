from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

def admin_required(f):
    """Decorador para proteger rutas exclusivas de Administrador"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Acceso denegado: Se requieren privilegios de Administrador.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def management_required(f):
    """Decorador para proteger rutas exclusivas de Dirección (Management)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_management:
            flash("Acceso denegado: Se requieren privilegios de Dirección.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):
    """Decorador para proteger rutas exclusivas de Gerente (Manager)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_manager:
            flash("Acceso denegado: Se requieren privilegios de Gerente.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def assistant_manager_required(f):
    """Decorador para proteger rutas exclusivas de Subgerente (Assistant Manager)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_assistant_manager:
            flash("Acceso denegado: Se requieren privilegios de Subgerente.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def operations_required(f):
    """Decorador para proteger rutas exclusivas de Operaciones"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_operations:
            flash("Acceso denegado: Se requieren privilegios de Operaciones.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def finance_required(f):
    """Decorador para proteger rutas exclusivas de Finanzas"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_finance:
            flash("Acceso denegado: Se requieren privilegios de Finanzas.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function

def guest_required(f):
    """Decorador para verificar usuarios Invitados (Guest)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_guest:
            flash("Acceso denegado: Rol de Invitado requerido.", "danger")
            return redirect(url_for('security.login'))
        return f(*args, **kwargs)
    return decorated_function