from flask import Blueprint, render_template, redirect, url_for, flash, request
from app.logistics.requests.location_request import LocationForm
from app.logistics.services.register_location import register_location_service
from app.logistics.services.query_location import get_location_details
from app.logistics.services.update_location import update_location_service

# Definimos el Blueprint
location_bp = Blueprint('logistics', __name__)

@location_bp.route('/locations/edit/<int:location_id>', methods=['GET', 'POST'])
def edit_location(location_id):
    # 1. Buscamos la sede por ID (Usando tu lógica de query_location.py)
    from app.logistics.services.query_location import get_location_details
    location_data = get_location_details(location_id)
    form = LocationForm()

    if form.validate_on_submit():
        success, message = update_location_service(location_id, form)
        if success:
            flash(message, "success")
            # En lugar de redirect, renderizamos y pasamos success=True
            return render_template('logistics/edit_location.html', form=form, location_id=location_id, success=True)
        flash(message, "danger")
    
    if not location_data:
        flash("Sede no encontrada", "danger")
        return redirect(url_for('logistics.register_location'))

    # 2. Instanciamos el formulario
    form = LocationForm()

    # 3. Si es GET, cargamos los datos actuales en los campos
    if request.method == 'GET':
        form.name.data = location_data['name']
        form.state.data = location_data['state']
        form.address.data = location_data['address']
        form.phone.data = location_data['phone']
        # NUEVO: Debes poblar el ID oculto para que el validador lo reconozca
        form.location_id.data = location_id

    # 4. Si es POST y es válido, guardamos los cambios
    if form.validate_on_submit():
        # Aquí llamarás a tu nuevo servicio de editar (Paso 2 abajo)
        success, message = update_location_service(location_id, form)
        if success:
            flash(message, "success")
            return redirect(url_for('logistics.edit_location', location_id=location_id))
        flash(message, "danger")

    return render_template('logistics/edit_location.html', form=form, location_id=location_id)

@location_bp.route('/locations', methods=['GET', 'POST'])
def register_location():
    form = LocationForm()
    
    if form.validate_on_submit():
        # Llamamos a tu lógica de servicio que ya programaste
        success, message = register_location_service(form)
        
        if success:
            flash(message, "success")
            # Pasamos success=True para activar la redirección automática
            return render_template('logistics/register_location.html', form=form, success=True)
        flash(message, "danger")
            
    return render_template('logistics/register_location.html', form=form)

@location_bp.route('/check-name', methods=['POST'])
def check_name():
    data = request.get_json()
    name = data.get('name', '').strip()
    # Aseguramos que loc_id sea un entero para la base de datos
    try:
        loc_id = int(data.get('location_id')) if data.get('location_id') else 0
    except (ValueError, TypeError):
        loc_id = 0
    
    from app.models import Location
    # Buscamos una sede con ese nombre que NO sea la actual
    exists = Location.query.filter(Location.name == name, Location.id != loc_id).first()
    
    return {"available": not exists}

# app/logistics/routes/location_routes.py

@location_bp.route('/check-phone', methods=['POST'])
def check_phone():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    loc_id = data.get('location_id')
    
    from app.models import Location
    # Buscamos si el teléfono ya existe en otra sede
    try:
        loc_id = int(loc_id) if loc_id else 0
    except: loc_id = 0

    exists = Location.query.filter(Location.phone == phone, Location.id != loc_id).first()
    
    return {"available": not exists}