from app.models.waste_model import AuditLog
from flask_login import current_user

def obtener_alarmas_para_dashboard():
    # Buscamos directamente las alertas registradas en audit_logs
    query = AuditLog.query.filter(
        AuditLog.affected_table == 'inventory',
        AuditLog.severity == 'ALERTA'
    )
    
    # Si NO es administrador, filtramos estrictamente por las sedes permitidas del usuario
    if not current_user.is_admin:
        sedes_permitidas = [loc.id for loc in current_user.locations]
        query = query.filter(
            AuditLog.changed_data['location_id'].as_integer().in_(sedes_permitidas)
        )
        
    return query.order_by(AuditLog.timestamp.desc()).all()