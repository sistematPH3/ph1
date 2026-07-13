from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
from app.decorators.roles import management_required, manager_required, admin_required

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/director')
@login_required
@management_required
def director_dashboard():
    return render_template('dashboard/management_dashboard.html')

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
