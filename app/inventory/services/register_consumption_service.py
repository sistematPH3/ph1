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

def register_consumption(product_id, location_id, quantity, user_id, notes):
    inventory_item = RegisterConsumptionRepository.get_inventory_item(product_id, location_id)

    if not inventory_item:
        return {'success': False, 'message': 'No existe registro de inventario para este producto en la sede seleccionada'}

    if inventory_item.current_quantity < quantity:
        return {'success': False, 'message': 'Stock insuficiente en la sede para realizar el consumo'}

    RegisterConsumptionRepository.update_stock(inventory_item, quantity)

    return {'success': True, 'message': 'Consumo registrado exitosamente'}