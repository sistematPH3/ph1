from app.models.waste_model import AppParameter
from app import db

class WasteConfigRepository:
    @staticmethod
    def get_all_parameters():
        return AppParameter.query.all()

    @staticmethod
    def get_parameter_by_key(key):
        return AppParameter.query.filter_by(key=key).first()

    @staticmethod
    def update_parameter(key, value):
        param = AppParameter.query.filter_by(key=key).first()
        if param:
            param.value = str(value)
            db.session.commit()
            return param
        return None