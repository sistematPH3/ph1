from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
# Importamos el decorador que acabamos de crear
from app.decorators.roles import management_required

# 1. Definir el Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# 2. Definir las rutas dentro del Blueprint
@dashboard_bp.route('/director')
@login_required
@management_required  # <--- Aplicamos el decorador para proteger la ruta automáticamente
def director_dashboard():
    # Gracias al decorador, ya no necesitas el 'if' ni el 'flash' manual aquí.
    # Si el usuario no es 'management', el decorador se encarga de todo.
    return render_template('dashboard/management_dashboard.html')