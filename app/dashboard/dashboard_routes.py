from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.decorators.roles import (
    management_required,
    manager_required,
    assistant_manager_required,
    admin_required,
    finance_required,
    operations_required
)
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard
from app.dashboard.dashboard_service import get_subgerente_context

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    if current_user.is_management:
        return redirect(url_for('dashboard.director_dashboard'))
    elif current_user.is_manager:
        return redirect(url_for('dashboard.manager_dashboard'))
    elif current_user.is_admin:
        return redirect(url_for('dashboard.admin_dashboard'))
    elif current_user.is_finance:
        return redirect(url_for('dashboard.finance_dashboard'))
    elif current_user.is_operations:
        return redirect(url_for('dashboard.operations_dashboard'))
    elif current_user.is_assistant_manager:
        return redirect(url_for('dashboard.assistant_manager_dashboard'))
        
    flash("No tienes un rol permitido para visualizar el panel de control.", "danger")
    return redirect(url_for('security.login'))

@dashboard_bp.route('/director')
@login_required
@management_required
def director_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/management_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/manager-dashboard')
@login_required
@manager_required
def manager_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/manager_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/assistant-manager')
@login_required
@assistant_manager_required
def assistant_manager_dashboard():
    return render_template(
        'dashboard/assistant_manager_dashboard.html',
        **get_subgerente_context(current_user)
    )

@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/admin_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/finance')
@login_required
@finance_required
def finance_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/finance_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/operations')
@login_required
@operations_required
def operations_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/operations_dashboard.html', alarmas=alarmas)