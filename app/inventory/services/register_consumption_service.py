from app.models.inventory_model import db
from app.inventory.repositories.register_consumption_repository import RegisterConsumptionRepository

def get_consumption_form_data(user_id):
    user = RegisterConsumptionRepository.get_user_by_id(user_id)
    
    if not user:
        return [], False

    is_admin = user.role_id == 1

    if is_admin:
        locations = RegisterConsumptionRepository.get_all_sedes()
    else:
        locations = RegisterConsumptionRepository.get_user_locations(user_id)

    return locations, is_admin

def get_location_products(location_id):
    products = RegisterConsumptionRepository.get_products_in_inventory(location_id)
    return [{'id': p.id, 'name': p.name} for p in products]

def get_product_lots(location_id, product_id):
    return RegisterConsumptionRepository.get_product_lots(product_id, location_id)

def register_consumption(location_id, items, user_id):
    try:
        for item in items:
            product_id = item['product_id']
            quantity_to_consume = float(item['quantity'])
            notes = item.get('notes', '')
            specified_lot = item.get('lot_number')

            inventory_item = RegisterConsumptionRepository.get_inventory_item(product_id, location_id)

            if not inventory_item:
                db.session.rollback()
                return {'success': False, 'message': f'No existe registro de inventario para el insumo ID {product_id}.'}

            stock_actual = float(inventory_item.current_quantity)
            if stock_actual < quantity_to_consume:
                db.session.rollback()
                name = inventory_item.product.name if hasattr(inventory_item, 'product') else f"ID {product_id}"
                return {'success': False, 'message': f'Stock insuficiente para {name}. Stock disponible: {stock_actual:.2f}.'}

            available_lots = RegisterConsumptionRepository.get_product_lots(product_id, location_id)

            if specified_lot and specified_lot.strip():
                specified_lot_clean = specified_lot.strip()
                matching_lot = next((l for l in available_lots if l['lot_number'] == specified_lot_clean), None)
                
                if not matching_lot or matching_lot['quantity'] < quantity_to_consume:
                    db.session.rollback()
                    lot_disp = matching_lot['quantity'] if matching_lot else 0.0
                    return {
                        'success': False, 
                        'message': f'El lote {specified_lot_clean} solo dispone de {lot_disp:.2f} unidades. Cantidad solicitada: {quantity_to_consume:.2f}.'
                    }

                new_stock = stock_actual - quantity_to_consume
                inventory_item.current_quantity = new_stock
                RegisterConsumptionRepository.record_lot_consumption_audit(
                    inventory_item=inventory_item,
                    lot_number=specified_lot_clean,
                    quantity_consumed=quantity_to_consume,
                    previous_stock=stock_actual,
                    new_stock=new_stock,
                    user_id=user_id,
                    notes=notes
                )
            else:
                remaining_qty = quantity_to_consume
                current_global_stock = stock_actual

                for l in available_lots:
                    if remaining_qty <= 0:
                        break
                    lot_available = float(l['quantity'])
                    qty_from_lot = min(remaining_qty, lot_available)
                    
                    next_stock = current_global_stock - qty_from_lot
                    RegisterConsumptionRepository.record_lot_consumption_audit(
                        inventory_item=inventory_item,
                        lot_number=l['lot_number'],
                        quantity_consumed=qty_from_lot,
                        previous_stock=current_global_stock,
                        new_stock=next_stock,
                        user_id=user_id,
                        notes=notes
                    )
                    current_global_stock = next_stock
                    remaining_qty -= qty_from_lot

                if remaining_qty > 0:
                    next_stock = current_global_stock - remaining_qty
                    RegisterConsumptionRepository.record_lot_consumption_audit(
                        inventory_item=inventory_item,
                        lot_number='S/L',
                        quantity_consumed=remaining_qty,
                        previous_stock=current_global_stock,
                        new_stock=next_stock,
                        user_id=user_id,
                        notes=notes
                    )
                    current_global_stock = next_stock

                inventory_item.current_quantity = current_global_stock

        db.session.commit()
        return {'success': True, 'message': 'Consumo registrado exitosamente con trazabilidad FEFO.'}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'Error interno del servidor: {str(e)}'}