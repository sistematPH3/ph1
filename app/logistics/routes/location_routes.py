from flask import Blueprint, render_template, redirect, url_for, flash
from app.logistics.requests.location_request import LocationForm
from app.logistics.services.register_location import register_location_service

# Definimos el Blueprint
location_bp = Blueprint('logistics', __name__)

@location_bp.route('/locations', methods=['GET', 'POST'])
def register_location():
    form = LocationForm()
    
    if form.validate_on_submit():
        # Llamamos a tu lógica de servicio que ya programaste
        success, message = register_location_service(form)
        
        if success:
            flash(message, "success")
            return redirect(url_for('logistics.register_location'))
        else:
            flash(message, "danger")
            
    return render_template('logistics/register_location.html', form=form)