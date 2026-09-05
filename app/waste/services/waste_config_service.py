from app.waste.repositories.waste_config_repository import WasteConfigRepository
from app.waste.requests.waste_config_validators import WasteConfigValidators, WasteConfigValidationError


class WasteConfigService:

    @staticmethod
    def get_config_data(current_user_role_id: int = None):
        if current_user_role_id is not None:
            WasteConfigValidators.validate_admin_permission(current_user_role_id)
        
        parameters = WasteConfigRepository.get_all_parameters()
        return {param.key: param.value for param in parameters} if parameters else {}

    @staticmethod
    def update_configs(data: dict, current_user_role_id: int = None, user_id: int = None):
        if current_user_role_id is not None:
            WasteConfigValidators.validate_admin_permission(current_user_role_id)
            
        WasteConfigValidators.validate_waste_config_data(data)

        updated_results = []
        for key, value in data.items():
            updated_item = WasteConfigRepository.update_parameter(key, value)
            if updated_item:
                updated_results.append(updated_item)
                
        return updated_results