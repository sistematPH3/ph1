import time
from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, session
from flask_login import login_required, current_user
from app.decorators.roles import require_roles
from app.waste.requests.register_waste_validators import validate_register_waste_payload
from app.waste.repositories.register_waste_repository import RegisterWasteRepository
from app.waste.services.register_waste_service import (
    get_form_data,
    get_location_products,
    get_product_lots,
    register_waste,
    user_can_access_location,
)

register_waste_bp = Blueprint('register_waste', __name__)

OPERATIVE_ROLES = ('admin', 'management', 'manager', 'assistant_manager', 'operations')

def _coerce_positive_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return value

@register_waste_bp.route('/waste/merma/new', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def nueva_merma():
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id') or getattr(current_user, 'id', None)
    if user_id is None:
        user_id = getattr(current_user, 'id', None)

    locations, is_admin, waste_types = get_form_data(user_id)

    from app.inventory.services.lot_availability_service import obtener_vencidos_para_dashboard
    vencidos = obtener_vencidos_para_dashboard(current_user)

    single_location = None
    if not is_admin and len(locations) == 1:
        single_location = locations[0]

    # --- Deep link desde alarma de vencidos ---
    alarm_prefill = None
    origin = request.args.get('origin')
    lock = request.args.get('lock')

    if origin == 'alarma_vencido' and lock == '1':
        # Revalidar en servidor: sede, lote vencido, cantidad válida
        location_id = request.args.get('location_id', type=int)
        product_id = request.args.get('product_id', type=int)
        lot_number = request.args.get('lot_number', type=str)
        quantity = request.args.get('quantity', type=float)

        # Validar parámetros obligatorios
        if not all([location_id, product_id, lot_number, quantity is not None]):
            flash('Parámetros de alarma incompletos.', 'danger')
            return redirect(url_for('register_waste.nueva_merma'))

        # Verificar acceso a la sede
        if not user_can_access_location(user_id, location_id):
            flash('No tienes permisos para acceder a esta sede.', 'danger')
            return redirect(url_for('register_waste.nueva_merma'))

        # Verificar que la sede es Central y si permite vencidos
        if location_id == 1 and not RegisterWasteRepository.vencido_permitido_en_central():
            flash('La Sede Central no permite registro de vencidos.', 'danger')
            return redirect(url_for('register_waste.nueva_merma'))

        # Revalidar que el lote sigue vencido y tiene saldo
        vencidos_loc = RegisterWasteRepository.get_expired_lots(location_id)
        lote_encontrado = None
        for v in vencidos_loc:
            if v['product_id'] == product_id and v['lot_number'] == str(lot_number).strip():
                lote_encontrado = v
                break

        if not lote_encontrado:
            flash('El lote ya no está vencido o no tiene saldo disponible.', 'warning')
            return redirect(url_for('register_waste.nueva_merma'))

        # Validar cantidad no supera saldo
        if quantity > lote_encontrado['quantity'] + 1e-9:
            flash(f'Cantidad solicitada ({quantity}) supera el saldo disponible ({lote_encontrado["quantity"]}).', 'danger')
            return redirect(url_for('register_waste.nueva_merma'))

        # Verificar que el tipo VENCIDO existe y está activo
        waste_type_vencido = next((wt for wt in RegisterWasteRepository.get_waste_types() if wt.code == 'VENCIDO' and wt.is_active), None)
        if not waste_type_vencido:
            flash('El tipo de merma VENCIDO no está configurado.', 'danger')
            return redirect(url_for('register_waste.nueva_merma'))

        # Persistir la alarma validada en la sesión: el POST solo acepta estos datos.
        session['alarma_vencido'] = {
            'location_id': location_id,
            'product_id': product_id,
            'lot_number': str(lot_number).strip(),
            'quantity': float(quantity),
        }

        # Armar prefill para el template
        alarm_prefill = {
            'location_id': location_id,
            'product_id': product_id,
            'lot_number': str(lot_number).strip(),
            'quantity': float(quantity),
            'waste_type_id': waste_type_vencido.id,
            'waste_type_name': waste_type_vencido.name,
            'product_name': lote_encontrado['product_name'],
            'expiration_date': lote_encontrado['expiration_date'],
        }
    # --- Fin deep link ---

    return render_template(
        'waste/register_waste.html',
        locations=locations,
        is_admin=is_admin,
        single_location=single_location,
        vencidos=vencidos,
        alarm_prefill=alarm_prefill,
    )

@register_waste_bp.route('/api/waste/locations/<int:location_id>/types', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def fetch_location_types(location_id):
    if not user_can_access_location(
            session.get('user_id') or session.get('_user_id') or session.get('id')
            or getattr(current_user, 'id', None), location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar esta sede.'}), 403

    waste_types = RegisterWasteRepository.get_waste_types()

    result = []
    for wt in waste_types:
        if location_id == 1 and not wt.applies_central and wt.code != 'VENCIDO':
            continue
        result.append({
            'id': wt.id,
            'name': wt.name,
            'code': wt.code,
            'description': wt.description,
            'requires_approval': bool(wt.requires_approval),
        })

    return jsonify({'success': True, 'types': result}), 200

@register_waste_bp.route('/api/waste/locations/<int:location_id>/products', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def fetch_location_products(location_id):
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id') or getattr(current_user, 'id', None)
    if not user_can_access_location(user_id, location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar el inventario de esta sede.'}), 403

    products = get_location_products(location_id)
    return jsonify({'success': True, 'products': products}), 200

@register_waste_bp.route('/api/waste/locations/<int:location_id>/products/<int:product_id>/lots', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def fetch_product_lots(location_id, product_id):
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id') or getattr(current_user, 'id', None)
    if not user_can_access_location(user_id, location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar los lotes de esta sede.'}), 403

    lots = get_product_lots(location_id, product_id)
    return jsonify({'success': True, 'lots': lots}), 200

@register_waste_bp.route('/api/waste/locations/<int:location_id>/vencidos', methods=['GET'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def fetch_location_vencidos(location_id):
    user_id = session.get('user_id') or session.get('_user_id') or session.get('id') or getattr(current_user, 'id', None)
    if not user_can_access_location(user_id, location_id):
        return jsonify({'success': False, 'message': 'No tienes permisos para consultar los vencidos de esta sede.'}), 403

    try:
        vencidos = RegisterWasteRepository.get_expired_lots(location_id)
    except Exception:
        vencidos = []
    return jsonify({'success': True, 'vencidos': vencidos}), 200

@register_waste_bp.route('/api/waste/evidence', methods=['POST'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def subir_foto():
    from app.integrations.imgbb.imgbb_services import upload_invoice_image

    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No se recibió la imagen.'}), 400

    file = request.files['image']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Archivo de imagen inválido.'}), 400

    if not (file.content_type or '').startswith('image/'):
        return jsonify({'success': False, 'message': 'Solo se permiten archivos de imagen.'}), 400

    image_bytes = file.read()
    if len(image_bytes) > 5 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'La imagen no puede superar los 5 MB.'}), 400

    try:
        filename = file.filename
        memory_file = io.BytesIO(image_bytes)
        memory_file.filename = filename
        url = upload_invoice_image(memory_file)
        return jsonify({'success': True, 'url': url}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'No se pudo subir la evidencia: {str(e)}'}), 400

@register_waste_bp.route('/waste/merma/new', methods=['POST'])
@login_required
@require_roles(*OPERATIVE_ROLES)
def crear_merma():
    now = time.time()
    last_submit = session.get('last_waste_submit_time', 0)
    if now - last_submit < 3.0:
        return jsonify({'success': False, 'message': 'Ya se está procesando un registro. Por favor, espere.'}), 429
    session['last_waste_submit_time'] = now

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        form = request.form
        items_raw = form.get('items', '[]')
        items = []
        if isinstance(items_raw, str):
            try:
                import json as _json
                items = _json.loads(items_raw)
            except (_json.JSONDecodeError, TypeError):
                items = []
        location_id = form.get('location_id', type=int)
        location_id = location_id if location_id is not None else form.get('location_id')
        data = {
            'location_id': _coerce_positive_int(location_id),
            'items': items,
            'evidence_url': form.get('evidence_url') or None,
            'notes': form.get('notes'),
            'request_id': form.get('request_id'),
        }

    # --- Bloqueo mono-ítem para deep link desde alarma de vencidos ---
    origin = data.get('origin') if isinstance(data, dict) else None
    if origin == 'alarma_vencido':
        items = data.get('items', []) if isinstance(data.get('items'), list) else []
        if len(items) != 1:
            return jsonify({'success': False, 'message': 'La alarma de vencidos solo permite un ítem.'}), 400
        item = items[0]
        required = ('product_id', 'lot_number', 'quantity', 'waste_type_id')
        for f in required:
            if f not in item:
                return jsonify({'success': False, 'message': f'Falta campo obligatorio: {f}'}), 400

        try:
            qty = float(item.get('quantity'))
            loc_id = int(data.get('location_id'))
            product_id = int(item.get('product_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Los campos (sede, producto, cantidad) son inválidos.'}), 400

        alarm = session.get('alarma_vencido')
        if not alarm:
            return jsonify({'success': False, 'message': 'Los datos de la alarma expiraron: vuelve a entrar desde el cuadro de vencidos.'}), 400

        # La ubicación debe ser la misma que validó el GET del deep link.
        if (loc_id != alarm['location_id']
                or product_id != alarm['product_id']
                or str(item.get('lot_number', '')).strip() != alarm['lot_number']
                or abs(qty - alarm['quantity']) > 1e-6):
            return jsonify({'success': False, 'message': 'Los datos enviados no coinciden con la alarma original.'}), 400

        # El motivo debe ser VENCIDO (tipo activo).
        wt_vencido = next((wt for wt in RegisterWasteRepository.get_waste_types() if wt.code == 'VENCIDO' and wt.is_active), None)
        try:
            item_waste_type_id = int(item.get('waste_type_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'El tipo de merma debe ser VENCIDO.'}), 400
        if not wt_vencido or item_waste_type_id != wt_vencido.id:
            return jsonify({'success': False, 'message': 'El tipo de merma debe ser VENCIDO.'}), 400

        # Revalidación en vivo: el lote sigue vencido y la cantidad no supera el saldo.
        lote = next((v for v in RegisterWasteRepository.get_expired_lots(loc_id)
                     if v['product_id'] == product_id and v['lot_number'] == str(item.get('lot_number', '')).strip()), None)
        if not lote:
            return jsonify({'success': False, 'message': 'El lote ya no está vencido o no tiene saldo disponible.'}), 400
        if qty > lote['quantity'] + 1e-9:
            return jsonify({'success': False, 'message': f'La cantidad ({qty}) supera el saldo disponible ({lote["quantity"]}).'}), 400
    # --- Fin bloqueo alarma ---

    validation = validate_register_waste_payload(data)
    if not validation['is_valid']:
        return jsonify({'success': False, 'errors': validation['errors']}), 400

    user_id = session.get('user_id') or session.get('_user_id') or session.get('id') or getattr(current_user, 'id', None)
    if user_id is None:
        user_id = getattr(current_user, 'id', None)

    if not user_can_access_location(user_id, data.get('location_id')):
        return jsonify({'success': False, 'message': 'No tienes permisos para registrar merma en esta sede.'}), 403

    result = register_waste(
        user_id=user_id,
        location_id=data['location_id'],
        items=data['items'],
        evidence_url=data.get('evidence_url'),
        notes=data.get('notes'),
        request_id=data.get('request_id'),
    )

    if result['success']:
        session.pop('alarma_vencido', None)
        return jsonify(result), 200
    else:
        return jsonify(result), 400