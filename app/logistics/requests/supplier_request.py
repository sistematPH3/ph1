class SupplierRequest:
    def __init__(self, form_data):
        self.name = form_data.get('name', '').strip()
        self.tax_id = form_data.get('tax_id', '').strip()
        self.contact_name = form_data.get('contact_name', '').strip()
        self.phone = form_data.get('phone', '').strip()
        self.email = form_data.get('email', '').strip()
        self.status = form_data.get('status', 'Active').strip()

    def is_valid(self):
        # Validaciones básicas de presencia y longitud según tu BD
        if not self.name or len(self.name) > 150: return False
        if not self.tax_id or len(self.tax_id) > 20: return False
        if not self.contact_name or len(self.contact_name) > 100: return False
        if not self.phone or len(self.phone) > 20: return False
        if not self.email or len(self.email) > 100: return False
        return True