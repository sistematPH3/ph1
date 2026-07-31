from flask import render_template, jsonify
from flask_login import login_required, current_user
from app.inventory import inventory_bp
from app.inventory.requests.inventory_views_validators import InventoryViewRequest
from app.inventory.services.inventory_views_service import InventoryViewService

@inventory_bp.route('/views', methods=['GET'])
@login_required
def render_inventory_views():
    filter_params = InventoryViewRequest.get_filter_params()
    context = InventoryViewService.get_inventory_for_user(current_user, filter_params)
    return render_template('inventory/inventory_views.html', **context)


@inventory_bp.route('/api/list', methods=['GET'])
@login_required
def get_inventory_api():
    """Endpoint en JSON para actualizar la tabla dinámicamente vía AJAX."""
    try:
        filter_params = InventoryViewRequest.get_filter_params()
        context = InventoryViewService.get_inventory_for_user(current_user, filter_params)
        
        inventory_list = context.get('inventory', []) or []
        items = []

        for item in inventory_list:
            prod_sku = item.product.sku if item and item.product else 'N/A'
            prod_name = item.product.name if item and item.product else 'Sin Nombre'
            
            # Revisa de forma segura si la propiedad es 'unit_of_measure' o 'unit'
            prod_unit = getattr(item.product, 'unit_of_measure', getattr(item.product, 'unit', 'UN')) if item and item.product else 'UN'
            
            loc_name = item.location.name if item and item.location else 'Sin Ubicación'
            
            curr_qty = float(item.current_quantity) if item and item.current_quantity is not None else 0.0
            min_stock = float(item.min_stock) if item and item.min_stock is not None else 0.0

            items.append({
                'sku': prod_sku,
                'product_name': prod_name,
                'unit': prod_unit,
                'location_name': loc_name,
                'current_quantity': curr_qty,
                'min_stock': min_stock,
                'is_low_stock': curr_qty <= min_stock
            })
            
        return jsonify({
            'success': True,
            'selected_location_id': context.get('selected_location_id'),
            'items': items
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'items': []
        }), 500