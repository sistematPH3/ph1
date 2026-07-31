from app.inventory.repositories.inventory_views_repository import InventoryViewRepository

class InventoryViewService:

    @staticmethod
    def get_inventory_for_user(current_user, filter_params):
        search_term = filter_params.get('search_term')
        selected_location_id = filter_params.get('location_id')
        
        # Validación de Administrador
        role_name = current_user.role.name.lower() if (current_user and current_user.role) else ''
        is_admin = 'admin' in role_name or current_user.role_id == 1
        
        if is_admin:
            locations_list = InventoryViewRepository.get_all_active_locations()
            
            # SI NO HAY SEDE SELECCIONADA -> Seleccionar por defecto Almacén Central (primera sede activa)
            if not selected_location_id and locations_list:
                selected_location_id = locations_list[0].id
            
            if selected_location_id:
                inventory_data = InventoryViewRepository.get_inventory_by_location(selected_location_id, search_term)
            else:
                inventory_data = InventoryViewRepository.get_all_inventory(search_term)
                
            return {
                'is_admin': True,
                'inventory': inventory_data,
                'available_locations': locations_list,
                'selected_location_id': selected_location_id
            }
        
        else:
            # Lógica para Gerente de Sede
            assigned_locations = InventoryViewRepository.get_user_assigned_locations(current_user.id)
            
            if assigned_locations:
                user_location_id = assigned_locations[0].id
                inventory_data = InventoryViewRepository.get_inventory_by_location(user_location_id, search_term)
                location_name = assigned_locations[0].name
            else:
                inventory_data = []
                location_name = "Sin Sede Asignada"

            return {
                'is_admin': False,
                'inventory': inventory_data,
                'available_locations': assigned_locations,
                'assigned_location_name': location_name,
                'selected_location_id': assigned_locations[0].id if assigned_locations else None
            }