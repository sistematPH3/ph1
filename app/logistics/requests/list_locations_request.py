class ListLocationsRequest:
    def __init__(self, data):
        # Para un GET simple usualmente no hay mucha validación, 
        # pero podrías validar filtros de búsqueda aquí.
        self.search_term = data.get('search', '').strip()