from flask import Blueprint, render_template, redirect, url_for, flash
from app.logistics.requests.location_request import LocationForm
from app.logistics.services.register_location import register_location_service

location_bp = Blueprint('location_routes_bp', __name__)

@location_bp.route('/locations', methods=['GET', 'POST'])
def register_location():
    form = LocationForm()
    
    if form.validate_on_submit():
        success, message = register_location_service(form)
        
        if success:
            flash(message, "success")
            return redirect(url_for('location_routes_bp.register_location'))
        else:
            flash(message, "danger")
            
    return render_template('logistics/register_location.html', form=form)