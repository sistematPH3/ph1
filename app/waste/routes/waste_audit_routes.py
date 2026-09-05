from decimal import Decimal
from datetime import datetime, date, timezone
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.inventory_model import Inventory, Product
from app.models.waste_model import AuditLog, WasteType, Waste
from app.models.logistics_model import Location
from app.waste.services.waste_audit_service import WasteAuditService
from app.waste.requests.waste_audit_validators import validate_audit_filters
from app.decorators.roles import require_roles
import json

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
    raw_audit_trail = WasteAuditService.get_formatted_audit_trail(current_user, {})

    # Normalizar los datos para evitar fallos si 'changed_data' o 'details' llegaron como string
    audit_trail = []
    for item in raw_audit_trail:
        if isinstance(item, dict):
            # Si cambió_data o un campo interno viene como string JSON, se parsea a dict
            changed = item.get('changed_data') or item.get('details')
            if isinstance(changed, str):
                try:
                    item['changed_data'] = json.loads(changed)
                except (json.JSONDecodeError, TypeError):
                    item['changed_data'] = {'detalle': changed}
            audit_trail.append(item)
        else:
            # Si el elemento completo de la lista era un string
            audit_trail.append({'detalle': str(item)})

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

def make_json_safe(data):
    """
    Serializa y vuelve a cargar la estructura garantizando que NO existan 
    objetos Decimal, datetime u otros tipos no compatibles con JSON.
    """
    def default_converter(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return str(obj)

    return json.loads(json.dumps(data, default=default_converter))


@waste_audit_bp.route('/api/revert/<int:log_id>', methods=['POST'])
@login_required
@require_roles('admin')
def revertir_merma_api(log_id):
    data = request.get_json() or {}
    reason = data.get('motivo_reversion', '').strip()

    if not reason or len(reason) < 15:
        return jsonify({
            'success': False,
            'errors': ['El motivo de la anulación es obligatorio y debe tener al menos 15 caracteres.']
        }), 400

    try:
        original_log = AuditLog.query.get_or_404(log_id)
        user_name = getattr(current_user, 'name', None) or getattr(current_user, 'email', None) or 'admin'
        
        # 1. Deserializar datos originales de forma segura
        raw_data = original_log.changed_data or {}
        if isinstance(raw_data, str):
            try:
                original_data = json.loads(raw_data)
            except Exception:
                original_data = {}
        elif isinstance(raw_data, dict):
            original_data = dict(raw_data)
        else:
            original_data = {}

        # 2. Consultar modelo Waste si existe merma_id
        merma_id = original_data.get('merma_id') or original_data.get('waste_id')
        waste_obj = None
        if merma_id:
            try:
                waste_obj = Waste.query.get(int(merma_id))
                if waste_obj:
                    waste_obj.status = 'REVERTIDO'
            except Exception:
                pass

        # 3. Recopilar lista de productos a restituir
        items_a_procesar = []

        # Opción A: Obtener directamente desde los detalles relacionales de la Merma
        if waste_obj and hasattr(waste_obj, 'details') and waste_obj.details:
            for detail in waste_obj.details:
                items_a_procesar.append({
                    'product_id': detail.product_id,
                    'producto_nombre': None,
                    'cantidad': float(detail.quantity or 0)
                })

        # Opción B: Si no hay detalles relacionales, usar el JSON original
        if not items_a_procesar:
            productos_json = (
                original_data.get('productos') or 
                original_data.get('detalles') or 
                original_data.get('items') or 
                []
            )

            for item in productos_json:
                if isinstance(item, dict):
                    p_id = item.get('product_id') or item.get('producto_id')
                    p_name = (
                        item.get('producto') or 
                        item.get('product_name') or 
                        item.get('nombre') or 
                        item.get('descripcion')
                    )
                    try:
                        cant = float(item.get('cantidad') or item.get('quantity') or item.get('qty') or 0)
                    except (ValueError, TypeError):
                        cant = 0.0

                    items_a_procesar.append({
                        'product_id': p_id,
                        'producto_nombre': p_name,
                        'cantidad': cant
                    })

        # 4. Restituir el stock buscando por ID o por Nombre del Producto
        # Obtener la sede de origen de la merma o del log original
        location_id = getattr(original_log, 'location_id', None)
        if not location_id and waste_obj:
            location_id = waste_obj.location_id

        # 4. Restituir el stock en la tabla Inventory por Sede
        productos_restituidos = []
        for item in items_a_procesar:
            prod_id = item.get('product_id')
            prod_name = item.get('producto_nombre')
            cantidad = item.get('cantidad', 0.0)

            if cantidad <= 0:
                continue

            product = None

            # Búsqueda 1: Por ID
            if prod_id:
                try:
                    product = Product.query.get(int(prod_id))
                except (ValueError, TypeError):
                    product = None

            # Búsqueda 2: Por Nombre (si falló el ID)
            if not product and prod_name:
                clean_name = str(prod_name).strip()
                product = Product.query.filter(Product.name.ilike(clean_name)).first()

            # Incrementar el inventario en la sede correspondiente
            if product and location_id:
                inventory_item = Inventory.query.filter_by(
                    location_id=location_id,
                    product_id=product.id
                ).first()

                if inventory_item:
                    inventory_item.current_quantity = float(inventory_item.current_quantity or 0.0) + cantidad
                else:
                    # Crear el registro de inventario para la sede si no existía
                    inventory_item = Inventory(
                        location_id=location_id,
                        product_id=product.id,
                        current_quantity=cantidad
                    )
                    db.session.add(inventory_item)

                productos_restituidos.append({
                    'product_id': product.id,
                    'producto': product.name,
                    'cantidad_restituida': cantidad
                })

        # 5. Crear el registro de auditoría de la reversión
        new_changed_data = make_json_safe({
            'evento': 'REVERSION',
            'estado': 'REVERTIDO',
            'original_audit_id': original_log.id,
            'merma_id': merma_id,
            'motivo_reversion': reason,
            'revertido_por': user_name,
            'productos_restituidos': productos_restituidos,
            'impacto_stock': 'Restituido al inventario (+ Stock devuelto)'
        })

        location_id = getattr(original_log, 'location_id', None)
        reversion_audit = AuditLog(
            user_id=current_user.id,
            location_id=location_id,
            action='MERMA',
            severity='CRITICO',
            timestamp=datetime.now(timezone.utc),
            changed_data=new_changed_data
        )

        # 6. Actualizar el estado del evento original
        original_data['estado'] = 'REVERTIDO'
        original_log.changed_data = make_json_safe(original_data)

        db.session.add(reversion_audit)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'La merma ha sido anulada con éxito y el stock fue restituido al inventario.'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'errors': [f'Error interno del servidor: {str(e)}']
        }), 500

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