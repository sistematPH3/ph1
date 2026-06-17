class SupplierRequest:
    def __init__(self, form_data):
        self.name = form_data.get('name', '').strip()
        self.tax_id = form_data.get('tax_id', '').strip()
        self.contact_name = form_data.get('contact_name', '').strip()
        self.phone = form_data.get('phone', '').strip()
        self.email = form_data.get('email', '').strip()
        self.status = form_data.get('status', 'Active').strip()

    def validate(self):
        if not self.name or len(self.name) > 150:
            raise ValueError("El nombre es obligatorio y no debe exceder 150 caracteres.")
        if not self.tax_id or len(self.tax_id) > 20:
            raise ValueError("El RIF es obligatorio y no debe exceder 20 caracteres.")
        if self.contact_name and len(self.contact_name) > 100:
            raise ValueError("El nombre de contacto no debe exceder 100 caracteres.")
        if self.phone and len(self.phone) > 20:
            raise ValueError("El teléfono no debe exceder 20 caracteres.")
        if self.email and len(self.email) > 100:
            raise ValueError("El correo electrónico no debe exceder 100 caracteres.")
        if self.status not in ['Active', 'Inactive']:
            raise ValueError("El estado seleccionado no es válido.")