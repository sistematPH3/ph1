import io
import time
from flask import Blueprint, request, jsonify, render_template, session
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

    vencidos = []
    try:
        for loc in locations:
            if loc.id == 1 and not RegisterWasteRepository.vencido_permitido_en_central():
                continue
            for v in RegisterWasteRepository.get_expired_lots(loc.id):
                v = dict(v)
                v['location_id'] = loc.id
                v['location_name'] = loc.name
                vencidos.append(v)
    except Exception:
        vencidos = []
    vencidos.sort(key=lambda v: (v['location_name'], v['expiration_date']))

    single_location = None
    if not is_admin and len(locations) == 1:
        single_location = locations[0]

    locked_type_code = (request.args.get('type') or '').strip().upper() or None
    if locked_type_code:
        if locked_type_code not in {wt.code for wt in waste_types}:
            locked_type_code = None

    return render_template(
        'waste/register_waste.html',
        locations=locations,
        is_admin=is_admin,
        single_location=single_location,
        locked_type_code=locked_type_code,
        vencidos=vencidos,
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
        waste_type_id = form.get('waste_type_id', type=int)
        waste_type_id = waste_type_id if waste_type_id is not None else form.get('waste_type_id')
        data = {
            'location_id': _coerce_positive_int(location_id),
            'waste_type_id': _coerce_positive_int(waste_type_id),
            'items': items,
            'evidence_url': form.get('evidence_url') or None,
            'notes': form.get('notes'),
            'request_id': form.get('request_id'),
        }

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
        waste_type_id=data['waste_type_id'],
        items=data['items'],
        evidence_url=data.get('evidence_url'),
        notes=data.get('notes'),
        request_id=data.get('request_id'),
    )

    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 400