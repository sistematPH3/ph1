from datetime import datetime

class PurchaseManagementFilterRequest:
    def load(self, params):
        errors = {}
        validated_data = {}

        start_date_str = params.get('start_date')
        if start_date_str and start_date_str.strip():
            try:
                validated_data['start_date'] = datetime.strptime(start_date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                errors['start_date'] = ["La fecha de inicio debe tener el formato AAAA-MM-DD."]
        else:
            validated_data['start_date'] = None

        end_date_str = params.get('end_date')
        if end_date_str and end_date_str.strip():
            try:
                validated_data['end_date'] = datetime.strptime(end_date_str.strip(), '%Y-%m-%d').date()
            except ValueError:
                errors['end_date'] = ["La fecha fin debe tener el formato AAAA-MM-DD."]
        else:
            validated_data['end_date'] = None

        supplier_id_str = params.get('supplier_id')
        if supplier_id_str and supplier_id_str.strip():
            try:
                validated_data['supplier_id'] = int(supplier_id_str)
            except ValueError:
                errors['supplier_id'] = ["El identificador del proveedor debe ser un número entero."]
        else:
            validated_data['supplier_id'] = None

        status = params.get('status')
        if status and status.strip():
            status_clean = status.strip().upper()
            if status_clean in ["COMPLETED", "ANNULLED"]:
                validated_data['status'] = status_clean
            else:
                errors['status'] = ["El estado debe ser obligatoriamente 'COMPLETED' o 'ANNULLED'."]
        else:
            validated_data['status'] = None

        if errors:
            raise ValueError(errors)

        if validated_data['start_date'] and validated_data['end_date']:
            if validated_data['start_date'] > validated_data['end_date']:
                errors['start_date'] = ["La fecha de inicio no puede ser posterior a la fecha fin."]
                raise ValueError(errors)

        return validated_data