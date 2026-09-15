VALID_FORMATS = ('pdf', 'excel')


def validate_export_format(data):
    """Valida el formato de descarga (pdf/excel). Acepta 'xlsx' como alias."""
    errors = {}
    formato = (data.get('formato') or 'pdf').lower()
    if formato == 'xlsx':
        formato = 'excel'
    if formato not in VALID_FORMATS:
        errors['formato'] = 'Invalid format'
    data['formato'] = formato
    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
    }