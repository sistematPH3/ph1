from datetime import datetime

from app.extensions import db
from app.models.logistics_model import Location
from app.models.security_model import User


def obtener_nombres_sedes(location_ids, sede_unica):
    """Nombres de las sedes cubiertas por el documento (o la sede puntual)."""
    if sede_unica:
        loc = db.session.get(Location, sede_unica)
        return loc.name if loc else f'Sede #{sede_unica}'
    if not location_ids:
        return 'Sin sedes'
    nombres = []
    for lid in location_ids:
        loc = db.session.get(Location, lid)
        if loc:
            nombres.append(loc.name)
    return ', '.join(nombres) if nombres else 'Todas las sedes'


def obtener_nombre_autor(user_id):
    usuario = db.session.get(User, user_id) if user_id else None
    if usuario is None:
        return 'Usuario del sistema'
    return usuario.name


def construir_nombre_archivo(header, extension, user_id=None):
    """Nombre de descarga seguro: reporte-<metrica>-<fecha/hora>.<ext>"""
    _ = obtener_nombre_autor(user_id)
    base = (header.get('metric') or 'reporte').lower().replace('_', '-')
    marca = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"reporte-{base}-{marca}.{extension}"