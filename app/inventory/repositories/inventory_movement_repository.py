from app.models.waste_model import AuditLog
from flask_login import current_user

def obtener_movimientos_resta():
    """
    Obtiene el listado de restas de stock.
    Filtra por la sede asignada si el usuario no es administrador.
    """
    # Por ahora solo incluye el flujo de GASTO_COCINA
    query = AuditLog.query.filter(
        AuditLog.affected_table == 'inventory',
        AuditLog.action == 'GASTO_COCINA' 
    )
    
    if not current_user.is_admin:
        sedes_permitidas = [loc.id for loc in current_user.locations]
        query = query.filter(
            AuditLog.changed_data['location_id'].as_integer().in_(sedes_permitidas)
        )
        
    return query.order_by(AuditLog.timestamp.desc()).all()

def obtener_movimiento_por_id(movimiento_id):
    """Busca un registro de movimiento específico o devuelve 404."""
    return AuditLog.query.get_or_404(movimiento_id)