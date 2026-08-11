import json
from app.extensions import db
from app.models.waste_model import AuditLog
from app.models.logistics_model import Location
from flask_login import current_user
from sqlalchemy import or_

def obtener_alarmas_para_dashboard():
    # 1. Consultamos AuditLog haciendo JOIN con Location para traer el nombre de la sede
    query = db.session.query(
        AuditLog,
        Location.name.label('location_name')
    ).outerjoin(
        Location, AuditLog.location_id == Location.id
    ).filter(
        # Buscamos por severidad de alerta/crítico sin exigir affected_table
        AuditLog.severity.in_(['ALERTA', 'CRITICO'])
    )
    
    # 2. Filtrado por las sedes asignadas al usuario (si no es Administrador Global)
    if not current_user.is_admin:
        sedes_permitidas = [loc.id for loc in current_user.locations]
        if not sedes_permitidas:
            return []
            
        query = query.filter(
            or_(
                AuditLog.location_id.in_(sedes_permitidas),
                AuditLog.location_id.is_(None)
            )
        )
        
    resultados = query.order_by(AuditLog.timestamp.desc()).all()
    
    # 3. Mapeamos la estructura para que el HTML la renderice limpiamente
    alarmas = []
    for log, loc_name in resultados:
        data = log.changed_data or {}
        
        # Si vino guardado como string JSON, lo parseamos
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = {}
                
        alarmas.append({
            'location_name': loc_name or 'Almacén Principal',
            'product_name': data.get('product_name') or data.get('producto') or 'Insumo sin nombre',
            'new_quantity': data.get('new_quantity', 0.0),
            'min_stock': data.get('min_stock', 20.0) # Umbral por defecto
        })
        
    return alarmas