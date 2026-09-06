from app.waste.repositories.waste_config_repository import WasteConfigRepository


class WasteConfigService:

    @staticmethod
    def get_config_data():
        parameters = WasteConfigRepository.get_all_parameters()
        return {param.key: param.value for param in parameters} if parameters else {}

    @staticmethod
    def update_configs(data: dict):
        updated_results = []
        for key, value in data.items():
            updated_item = WasteConfigRepository.update_parameter(key, value)
            if updated_item:
                updated_results.append(updated_item)
        return updated_results