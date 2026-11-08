class ListProductsRequest:
    def __init__(self, data):
        # Captura el parámetro 'q' que viene de tu barra de búsqueda y limpia espacios vacíos
        self.search_query = data.get('q', '').strip()

    def is_valid(self):
        """
        Centraliza la regla de negocio de Diego: 
        Evitar términos de búsqueda exagerados (máximo 50 caracteres).
        """
        return len(self.search_query) <= 50