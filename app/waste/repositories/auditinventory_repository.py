from app.models.inventory_model import db
from app.models.logistics_model import Location
from app.models.security_model import User, user_locations
from sqlalchemy import text

class AuditInventoryRepository:
    
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_user_allowed_locations(user_id):
        loc_ids_result = db.session.query(user_locations.c.location_id).filter(user_locations.c.user_id == user_id).all()
        return [row[0] for row in loc_ids_result]
        
    @staticmethod
    def get_all_locations():
        return Location.query.filter(Location.is_active == True).all()

    @staticmethod
    def get_audit_logs(allowed_locations=None, location_id_filter=None, severity_filter=None):
        query = db.session.query(
            db.Model.metadata.tables['audit_logs'],
            Location.name.label('location_name'),
            User.name.label('user_name')
        ).outerjoin( 
            Location, db.Model.metadata.tables['audit_logs'].c.location_id == Location.id
        ).outerjoin( 
            User, db.Model.metadata.tables['audit_logs'].c.user_id == User.id
        )

        # Filtro de sedes permitidas (para gerentes)
        if allowed_locations is not None:
            if not allowed_locations:
                return [] 
            
            # NUEVA LÓGICA: Si el usuario tiene acceso al Almacén Central (1), 
            # también le permitimos ver los registros huérfanos (None) que dejaron otros módulos.
            if 1 in allowed_locations:
                query = query.filter(
                    (db.Model.metadata.tables['audit_logs'].c.location_id.in_(allowed_locations)) |
                    (db.Model.metadata.tables['audit_logs'].c.location_id.is_(None))
                )
            else:
                query = query.filter(db.Model.metadata.tables['audit_logs'].c.location_id.in_(allowed_locations))
            
        # FILTRO DE SEDE (Manejo inteligente para Almacén Central)
        if location_id_filter is not None and location_id_filter != '':
            # Si el ID filtrado es 1 (Almacén Central), traemos también los NULL por si hay registros huérfanos manuales
            if location_id_filter == 1:
                query = query.filter(
                    (db.Model.metadata.tables['audit_logs'].c.location_id == 1) | 
                    (db.Model.metadata.tables['audit_logs'].c.location_id.is_(None))
                )
            else:
                query = query.filter(db.Model.metadata.tables['audit_logs'].c.location_id == location_id_filter)
            
        if severity_filter:
            query = query.filter(db.Model.metadata.tables['audit_logs'].c.severity == severity_filter)
            
        query = query.order_by(db.Model.metadata.tables['audit_logs'].c.timestamp.desc())
        
        return query.all()