# app/logistics/requests/location_request.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField
from wtforms.validators import DataRequired
from app.logistics.requests.locations_validators import LayoutValidators
from app.utils.constants import VENEZUELA_STATES

class LocationForm(FlaskForm):
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