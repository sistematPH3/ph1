from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.logistics.requests.location_request import LocationForm
from app.logistics.services.register_location import register_location_service
from app.logistics.services.query_location import get_location_details
from app.logistics.services.update_location import update_location_service
from app.decorators.roles import admin_required

location_bp = Blueprint('locations', __name__)

@location_bp.route('/locations/edit/<int:location_id>', methods=['GET', 'POST'])
@admin_required
def edit_location(location_id):
    location_data = get_location_details(location_id)
    if not location_data:
        flash("Sede no encontrada", "danger")
        return redirect(url_for('list_sedes_bp.list_sedes'))

    form = LocationForm()

    if request.method == 'GET':
        form.location_id.data = location_id
        form.name.data = location_data['name']
        form.state.data = location_data['state']
        form.address.data = location_data['detailed_address']
        form.phone.data = location_data['phone']
    
    elif request.method == 'POST':
        if form.validate_on_submit():
            if location_id == 1:
                form.name.data = 'Almacén Central'

            success, message = update_location_service(location_id, form)
            if success:
                flash(message, "success")
                return render_template('logistics/edit_location.html', form=form, location_id=location_id, success=True)
            
            flash(message, "danger")
        else:
            form.location_id.data = location_id

    return render_template('logistics/edit_location.html', form=form, location_id=location_id)

@location_bp.route('/locations', methods=['GET', 'POST'])
@admin_required
def register_location():
    form = LocationForm()
    
    if form.validate_on_submit():
        success, message = register_location_service(form)
        
        if success:
            flash(message, "success")
            return render_template('logistics/register_location.html', form=form, success=True)
        flash(message, "danger")
            
    return render_template('logistics/register_location.html', form=form)

@location_bp.route('/check-name', methods=['POST'])
@login_required
def check_name():
    data = request.get_json()
    name = data.get('name', '').strip()
    
    try:
        loc_id = int(data.get('location_id')) if data.get('location_id') else 0
    except (ValueError, TypeError):
        loc_id = 0
    
    from app.models import Location
    
    exists = Location.query.filter(
        Location.name.ilike(name), 
        Location.id != loc_id
    ).first()
    
    return {"available": exists is None}

@location_bp.route('/check-phone', methods=['POST'])
@login_required
def check_phone():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    loc_id = data.get('location_id')
    
    from app.models import Location
    
    try:
        loc_id = int(loc_id) if loc_id else 0
    except (ValueError, TypeError): 
        loc_id = 0

    exists = Location.query.filter(
        Location.phone == phone, 
        Location.id != loc_id
    ).first()
    
    return {"available": exists is None}