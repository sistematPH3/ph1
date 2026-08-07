from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.decorators.roles import management_required, manager_required, admin_required, finance_required
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    """Redirige dinámicamente al dashboard correcto según el rol del usuario"""
    if current_user.is_management:
        return redirect(url_for('dashboard.director_dashboard'))
    elif current_user.is_manager:
        return redirect(url_for('dashboard.manager_dashboard'))
    elif current_user.is_admin:
        return redirect(url_for('dashboard.admin_dashboard'))
    elif current_user.is_finance:
        return redirect(url_for('dashboard.finance_dashboard'))
    elif current_user.is_assistant_manager or current_user.is_operations:
        flash("Acceso concedido al sistema. Tu panel específico está en desarrollo.", "info")
        return redirect(url_for('inventory.list_products'))
        
    flash("No tienes un rol permitido para visualizar el panel de control.", "danger")
    return redirect(url_for('security.login'))


@dashboard_bp.route('/director')
@login_required
@management_required
def director_dashboard():
    # Obtiene las alarmas filtradas automáticamente por la sede del director
    alarmas = obtener_alarmas_para_dashboard()
    
    # Se las pasa a la plantilla HTML
    return render_template('dashboard/management_dashboard.html', alarmas=alarmas)


@dashboard_bp.route('/manager-dashboard')
@login_required
@manager_required
def manager_dashboard():
    return render_template('dashboard/manager_dashboard.html')


@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    return render_template('dashboard/admin_dashboard.html')


@dashboard_bp.route('/finance')
@login_required
@finance_required
def finance_dashboard():
    return render_template('dashboard/finance_dashboard.html')