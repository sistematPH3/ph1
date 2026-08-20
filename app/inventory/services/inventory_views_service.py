from app.inventory.repositories.inventory_views_repository import InventoryViewRepository

class InventoryViewService:

    @staticmethod
    def get_inventory_for_user(current_user, filter_params):
        search_term = filter_params.get('search_term')
        selected_location_id = filter_params.get('location_id')
        
        role_name = current_user.role.name.lower() if (current_user and current_user.role) else ''
        is_admin = 'admin' in role_name or current_user.role_id == 1
        
        if is_admin:
            locations_list = InventoryViewRepository.get_all_active_locations()
            
            if not selected_location_id and locations_list:
                selected_location_id = locations_list[0].id
            
            if selected_location_id:
                inventory_data = InventoryViewRepository.get_inventory_by_location(selected_location_id, search_term)
            else:
                inventory_data = InventoryViewRepository.get_all_inventory(search_term)

            alerts_summary = InventoryViewRepository.get_low_stock_counts_by_location()
            total_global_alerts = sum(item['count'] for item in alerts_summary)
                
            return {
                'is_admin': True,
                'inventory': inventory_data,
                'available_locations': locations_list,
                'selected_location_id': selected_location_id,
                'alerts_summary': alerts_summary,          
                'total_global_alerts': total_global_alerts
            }
        
        else:
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

    @staticmethod
    def get_lots_for_product(location_id, product_id):
        return InventoryViewRepository.get_product_lots_by_location(location_id, product_id)