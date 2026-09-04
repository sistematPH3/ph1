from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.waste_model import AuditLog, WasteType
from app.models.logistics_model import Location
from app.waste.services.waste_audit_service import WasteAuditService
from app.waste.requests.waste_audit_validators import validate_audit_filters
from app.decorators.roles import require_roles

waste_audit_bp = Blueprint('waste_audit', __name__, url_prefix='/waste/merma')

@waste_audit_bp.route('/audit', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def ver_auditoria():
    """Renderiza la vista principal pasando los datos directamente a Jinja2."""
    try:
        locations = Location.query.filter_by(is_active=True).all()
        # Mapear nombres de las sedes
        locations_list = [getattr(loc, 'nombre', None) or getattr(loc, 'name', '') for loc in locations]
        locations_list = [loc for loc in locations_list if loc]
    except Exception:
        locations_list = []

    # Obtener el historial completo
    audit_trail = WasteAuditService.get_formatted_audit_trail(current_user, {})

    return render_template(
        'waste/waste_audit.html', 
        audit_trail=audit_trail, 
        locations=locations_list
    )

@waste_audit_bp.route('/api/audit', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def auditoria_api():
    """Endpoint API que retorna los eventos en formato JSON."""
    errors = validate_audit_filters(request.args)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400
        
    filters = {
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'severity': request.args.get('severity')
    }
    
    audit_trail = WasteAuditService.get_formatted_audit_trail(current_user, filters)
    return jsonify({'success': True, 'data': audit_trail}), 200

@waste_audit_bp.route('/api/revert/<int:log_id>', methods=['POST'])
@login_required
@require_roles('admin', 'finance')
def revertir_merma_api(log_id):
    """Endpoint API para anular y revertir una merma aprobada."""
    data = request.get_json() or {}
    reason = data.get('motivo_reversion', '').strip()

    if not reason or len(reason) < 15:
        return jsonify({
            'success': False,
            'errors': ['El motivo de la anulación es obligatorio y debe tener al menos 15 caracteres.']
        }), 400

    # 1. Obtener la merma original
    original_log = AuditLog.query.get_or_404(log_id)
    user_name = getattr(current_user, 'name', None) or getattr(current_user, 'email', None) or 'admin'

    original_data = dict(original_log.changed_data or {})
    productos = original_data.get('productos', [])

    # 2. Registrar la nueva auditoría de severidad CRÍTICO
    reversion_audit = AuditLog(
        user_id=current_user.id,
        location_id=original_log.location_id,
        action='MERMA',
        severity='CRITICO',
        timestamp=datetime.now(timezone.utc),
        changed_data={
            'evento': 'REVERSION',
            'estado': 'REVERTIDO',
            'original_audit_id': original_log.id,
            'motivo_reversion': reason,
            'revertido_por': user_name,
            'productos': productos,
            'impacto_stock': 'Restituido al inventario (+ Stock devuelto)'
        }
    )

    # 3. Actualizar el estado del registro original
    updated_data = dict(original_log.changed_data or {})
    updated_data['estado'] = 'REVERTIDO'
    original_log.changed_data = updated_data

    # Guardar ambos cambios
    db.session.add(reversion_audit)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'La merma ha sido anulada con éxito y se registró en la auditoría.'
    }), 200

@waste_audit_bp.route('/locations/api/all', methods=['GET'])
@login_required
def get_all_locations():
    try:
        # Consulta de sedes activas desde la base de datos
        sedes = Location.query.filter_by(is_active=True).all()
        data = [getattr(sede, 'nombre', None) or getattr(sede, 'name', '') for sede in sedes]
        return jsonify({'success': True, 'data': [d for d in data if d]}), 200
    except Exception as e:
        return jsonify({'success': False, 'errors': [str(e)]}), 500

def obtener_tipos_merma_por_sede(location_id: int):
    """
    Sede Central (location_id = 1) solo maneja mermas de TEMPERATURA y ROBO_SOSPECHA.
    Las demás sedes (con cocina) disponen del catálogo completo.
    """
    if location_id == 1:
        return WasteType.query.filter(
            WasteType.is_active == True,
            WasteType.code.in_(['TEMPERATURA', 'ROBO_SOSPECHA'])
        ).all()
    
    return WasteType.query.filter(WasteType.is_active == True).all()