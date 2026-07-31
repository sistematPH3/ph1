from flask import request

class InventoryViewRequest:
    @staticmethod
    def get_filter_params():
        """
        Extrae y valida los parámetros de búsqueda y filtrado de la URL.
        """
        location_id = request.args.get('location_id', type=int)
        search_term = request.args.get('q', default='', type=str).strip()
        
        return {
            'location_id': location_id,
            'search_term': search_term
        }