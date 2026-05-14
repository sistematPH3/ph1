from wtforms.validators import ValidationError
import re

class LayoutValidators:
    """Validaciones generales para todo el sistema de Pizza Hut"""

    @staticmethod
    def validate_characters(form, field):
        """Evita que metan símbolos raros en nombres de sedes o usuarios"""
        if field.data and not re.match(r"^[a-zA-Z0-9 áéíóúÁÉÍÓÚñÑüÜ.]*$", field.data):
            raise ValidationError("El campo contine caracteres invalidos. Use solo letras y numeros.")

    @staticmethod
    def validate_phone(form, field):
        """Valida formato de teléfono (útil para Gestión de Sedes)"""
        pattern = r"^(0414|0424|0412|0416|0426|0212)\d{7}$"
        if field.data and not re.match(pattern, field.data):
            raise ValidationError("Formato telefonico invalido. Ejm: 02121234567")

    @staticmethod
    def validate_not_empty(form, field):
        """Asegura que no envíen solo espacios en blanco"""
        if field.data and not field.data.strip():
            raise ValidationError("No se permiten campos en blanco.")