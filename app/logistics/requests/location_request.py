# app/logistics/requests/location_request.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, ValidationError
from app.logistics.requests.locations_validators import LayoutValidators
from app.utils.constants import VENEZUELA_STATES
from app.models import Location

class LocationForm(FlaskForm):
    location_id = HiddenField() # Campo oculto para saber si estamos editando
    name = StringField('Nombre de la Sede', validators=[
        DataRequired(message="El nombre es obligatorio"), 
        LayoutValidators.validate_characters,
        LayoutValidators.validate_not_empty
    ])
    
    state = SelectField('Estado', choices=VENEZUELA_STATES, validators=[
        DataRequired(message="Debe seleccionar un estado")
    ])
    
    address = TextAreaField('Dirección Detallada', validators=[
        DataRequired(message="La dirección es obligatoria"),
        LayoutValidators.validate_not_empty
    ])
    
    phone = StringField('Teléfono de Contacto', validators=[
        DataRequired(message="El teléfono es obligatorio"),
        LayoutValidators.validate_phone
    ])
    
    def validate_name(self, name):
        # Buscamos si existe una sede con ese nombre
        existing_location = Location.query.filter_by(name=name.data).first()
        
        if existing_location:
            # Si estamos editando y el ID coincide, no hay problema
            # Si el ID es distinto o es un registro nuevo (sin ID), lanzamos error
            if str(existing_location.id) != str(self.location_id.data):
                raise ValidationError("Este nombre de sede ya se encuentra registrado.")