# app/validators.py

def validate_staff_update(data):
    errors = []
    
    # 1. Validar correo
    email = data.get('email')
    if not email or '@' not in email:
        errors.append("El correo electrónico no es válido.")
        
    # 2. Validar que el rol exista
    if not data.get('role_id'):
        errors.append("Debes seleccionar un rol válido.")
        
    # 3. Validar sedes (solo si no es admin, ya lo manejamos en el front)
    # Pero por seguridad, validamos que si no es admin, la lista de sedes no venga nula
    locations = data.get('locations')
    if locations is not None and not isinstance(locations, list):
        errors.append("El formato de las sedes es incorrecto.")
        
    return errors