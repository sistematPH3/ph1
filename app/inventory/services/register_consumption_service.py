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
            quantity = item['quantity']
            notes = item.get('notes', '')
            lot_number = item.get('lot_number')

            inventory_item = RegisterConsumptionRepository.get_inventory_item(product_id, location_id)

            if not inventory_item:
                db.session.rollback()
                return {'success': False, 'message': f'No existe registro de inventario para el insumo ID {product_id}. Lote abortado.'}

            if float(inventory_item.current_quantity) < float(quantity):
                db.session.rollback()
                name = inventory_item.product.name if hasattr(inventory_item, 'product') else f"ID {product_id}"
                return {'success': False, 'message': f'Stock insuficiente para {name}. Lote abortado para proteger el inventario.'}

            RegisterConsumptionRepository.update_stock(inventory_item, quantity, user_id, notes, lot_number)

        db.session.commit()
        return {'success': True, 'message': 'Lote de consumo registrado exitosamente.'}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'Error interno del servidor: {str(e)}'}