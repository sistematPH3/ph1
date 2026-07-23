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


# =========================================================================
# NUEVO DECORADOR DINÁMICO UNIVERSAL
# =========================================================================

def require_roles(*allowed_roles):
    """
    Decorador dinámico para verificar permisos pasando los roles permitidos 
    como argumentos de cadena (ej: @require_roles('admin', 'manager')).
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Acceso denegado: Por favor inicie sesión.", "danger")
                return redirect(url_for('security.login'))
            
            # Mapeo de los strings de roles con las propiedades de tu modelo User
            role_checks = {
                'admin': current_user.is_admin,
                'management': current_user.is_management,
                'manager': current_user.is_manager,
                'assistant_manager': current_user.is_assistant_manager,
                'operations': current_user.is_operations,
                'finance': current_user.is_finance,
                'guest': current_user.is_guest
            }
            
            # Valida si el usuario posee al menos uno de los roles solicitados
            has_permission = any(role_checks.get(role, False) for role in allowed_roles)
            
            if not has_permission:
                flash("Acceso denegado: No cuenta con los privilegios necesarios para esta acción.", "danger")
                return redirect(url_for('security.login'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator