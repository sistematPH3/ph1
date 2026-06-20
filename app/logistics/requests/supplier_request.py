import re

class SupplierRequest:
    def __init__(self, form_data):
        self.name = form_data.get('name', '').strip()
        self.tax_id = form_data.get('tax_id', '').strip()
        self.contact_name = form_data.get('contact_name', '').strip()
        self.phone = form_data.get('phone', '').strip()
        self.email = form_data.get('email', '').strip()

    def validate(self):
        if not self.name or len(self.name) > 150:
            raise ValueError("El nombre es obligatorio y no debe exceder 150 caracteres.")
        
        if not self.tax_id or len(self.tax_id) > 20:
            raise ValueError("El RIF es obligatorio y no debe exceder 20 caracteres.")
        
        if self.contact_name and len(self.contact_name) > 100:
            raise ValueError("El nombre de contacto no debe exceder 100 caracteres.")

        phone_regex = re.compile(r'^\+?[0-9][0-9\-\s]{7,18}[0-9]$')
        if not self.phone or not phone_regex.fullmatch(self.phone) or len(self.phone) > 20:
            raise ValueError("El teléfono es obligatorio y solo debe contener números (Ej. +58 412-0000000).")

        email_regex = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
        if not self.email or not email_regex.fullmatch(self.email) or len(self.email) > 100:
            raise ValueError("El correo electrónico es obligatorio y debe tener un formato válido con su '@'.")