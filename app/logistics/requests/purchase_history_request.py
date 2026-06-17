# app/logistics/requests/purchase_history_request.py
from datetime import datetime

class PurchaseHistoryFilterRequest:
    def load(self, params):
        errors = {}
        validated_data = {}

        start_date_str = params.get('start_date')
        if start_date_str:
            try:
                validated_data['start_date'] = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                errors['start_date'] = ["La fecha de inicio debe tener el formato AAAA-MM-DD."]

        end_date_str = params.get('end_date')
        if end_date_str:
            try:
                validated_data['end_date'] = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                errors['end_date'] = ["La fecha fin debe tener el formato AAAA-MM-DD."]

        supplier_id_str = params.get('supplier_id')
        if supplier_id_str:
            try:
                validated_data['supplier_id'] = int(supplier_id_str)
            except ValueError:
                errors['supplier_id'] = ["El identificador del proveedor debe ser un número entero."]

        status = params.get('status')
        if status:
            if status in ["COMPLETED", "ANNULLED"]:
                validated_data['status'] = status
            else:
                errors['status'] = ["El estado debe ser obligatoriamente 'COMPLETED' o 'ANNULLED'."]

        if errors:
            raise ValueError(errors)

        return validated_data

    def validate_dates(self, data):
        if data.get('start_date') and data.get('end_date'):
            if data['start_date'] > data['end_date']:
                raise ValueError({'start_date': ["La fecha de inicio no puede ser mayor que la fecha fin."]})
        return data