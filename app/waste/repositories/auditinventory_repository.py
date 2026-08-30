from app.models.inventory_model import db
from app.models.logistics_model import Location
from app.models.security_model import User, user_locations
from sqlalchemy import text
import json

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
    def get_audit_logs(allowed_locations=None, location_id_filter=None, severity_filter=None, start_date=None, end_date=None):
        audit_table = db.Model.metadata.tables['audit_logs']

        query = db.session.query(
            audit_table,
            Location.name.label('location_name'),
            User.name.label('user_name')
        ).outerjoin( 
            Location, audit_table.c.location_id == Location.id
        ).outerjoin( 
            User, audit_table.c.user_id == User.id
        )

        if allowed_locations is not None:
            if not allowed_locations:
                return [] 
            
            if 1 in allowed_locations:
                query = query.filter(
                    (audit_table.c.location_id.in_(allowed_locations)) |
                    (audit_table.c.location_id.is_(None))
                )
            else:
                query = query.filter(audit_table.c.location_id.in_(allowed_locations))
            
        if location_id_filter is not None and location_id_filter != '':
            if location_id_filter == 1:
                query = query.filter(
                    (audit_table.c.location_id == 1) | 
                    (audit_table.c.location_id.is_(None))
                )
            else:
                query = query.filter(audit_table.c.location_id == location_id_filter)
            
        if severity_filter:
            query = query.filter(audit_table.c.severity == severity_filter)

        if start_date:
            query = query.filter(audit_table.c.timestamp >= f"{start_date} 00:00:00")

        if end_date:
            query = query.filter(audit_table.c.timestamp <= f"{end_date} 23:59:59")
            
        query = query.order_by(audit_table.c.timestamp.desc())
        
        return query.all()

    @staticmethod
    def get_audit_logs_date_range(allowed_locations=None, location_id_filter=None):
        """
        Rango (mín, máx) de fechas donde existen registros de auditoría.
        Respeta la restricción de sedes pero NO los filtros de severidad/fecha:
        el calendario debe ofrecer el rango completo disponible.
        """
        audit_table = db.Model.metadata.tables['audit_logs']
        query = db.session.query(
            db.func.min(audit_table.c.timestamp),
            db.func.max(audit_table.c.timestamp)
        ).filter(audit_table.c.timestamp.isnot(None))

        if allowed_locations is not None:
            if not allowed_locations:
                return None, None

            if 1 in allowed_locations:
                query = query.filter(
                    (audit_table.c.location_id.in_(allowed_locations)) |
                    (audit_table.c.location_id.is_(None))
                )
            else:
                query = query.filter(audit_table.c.location_id.in_(allowed_locations))

        if location_id_filter is not None and location_id_filter != '':
            if location_id_filter == 1:
                query = query.filter(
                    (audit_table.c.location_id == 1) |
                    (audit_table.c.location_id.is_(None))
                )
            else:
                query = query.filter(audit_table.c.location_id == location_id_filter)

        min_ts, max_ts = query.first()
        return min_ts, max_ts

    @staticmethod
    def get_audit_log_by_id(log_id):
        table = db.Model.metadata.tables['audit_logs']
        return db.session.query(table).filter(table.c.id == log_id).first()

    @staticmethod
    def get_current_stock(location_id, product_id):
        query = text("""
            SELECT current_quantity FROM inventory 
            WHERE location_id = :loc_id AND product_id = :prod_id
        """)
        result = db.session.execute(query, {'loc_id': location_id, 'prod_id': product_id}).fetchone()
        return result[0] if result else 0.00

    @staticmethod
    def register_audit_adjustment(user_id, location_id, action_type, severity, product_id, product_name, prev_qty, new_qty, qty_changed, notes, original_log_id=None, new_original_severity=None):
        insert_log_query = text("""
            INSERT INTO audit_logs (user_id, location_id, action, severity, timestamp, changed_data)
            VALUES (:user_id, :location_id, :action, :severity, NOW(), :changed_data)
        """)
        
        changed_data_json = json.dumps({
            'product_id': product_id,
            'product_name': product_name,
            'previous_quantity': prev_qty,
            'new_quantity': new_qty,
            'quantity_changed': qty_changed,
            'notes': notes
        })

        db.session.execute(insert_log_query, {
            'user_id': user_id,
            'location_id': location_id,
            'action': action_type,
            'severity': severity,
            'changed_data': changed_data_json
        })

        update_stock_query = text("""
            UPDATE inventory
            SET current_quantity = :new_qty
            WHERE location_id = :loc_id AND product_id = :prod_id
        """)
        
        db.session.execute(update_stock_query, {
            'new_qty': new_qty,
            'loc_id': location_id,
            'prod_id': product_id
        })

        if original_log_id and new_original_severity:
            update_severity_query = text("""
                UPDATE audit_logs 
                SET severity = :sev 
                WHERE id = :log_id
            """)
            db.session.execute(update_severity_query, {
                'sev': new_original_severity, 
                'log_id': original_log_id
            })
        
        db.session.commit()