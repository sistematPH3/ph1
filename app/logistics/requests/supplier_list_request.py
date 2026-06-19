

class SupplierListFilterRequest:
    def load(self, params):
        """
        Procesa, limpia y valida los parámetros de búsqueda y filtrado de proveedores.
        Retorna un diccionario con la data limpia.
        """
        errors = {}
        validated_data = {}

        
        search = params.get('search')
        if search and search.strip():
            validated_data['search'] = search.strip()
        else:
            validated_data['search'] = None

        
        status = params.get('status')
        if status and status.strip():
            status_clean = status.strip().upper()
            if status_clean in ["ACTIVE", "INACTIVE"]:
                validated_data['status'] = status_clean
            else:
                errors['status'] = ["El estado debe ser obligatoriamente 'ACTIVE' o 'INACTIVE'."]
        else:
            validated_data['status'] = None

        if errors:
            raise ValueError(errors)

        return validated_data