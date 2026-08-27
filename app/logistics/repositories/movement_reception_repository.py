from decimal import Decimal
from datetime import datetime
from sqlalchemy import text
from app import db

class MovementReceptionRepository:

    @staticmethod
    def get_movement_by_id(movement_id):
        sql = text("""
            SELECT 
                m.id,
                m.type,
                m.origin_location_id,
                m.destination_location_id,
                m.date,
                m.user_id,
                m.status,
                m.received_by_id,
                m.resolved_by_id,
                m.resolution_notes,
                loc_orig.name AS origin_name,
                loc_dest.name AS destination_name
            FROM movements m
            INNER JOIN locations loc_orig ON m.origin_location_id = loc_orig.id
            INNER JOIN locations loc_dest ON m.destination_location_id = loc_dest.id
            WHERE m.id = :movement_id
        """)
        return db.session.execute(sql, {"movement_id": movement_id}).mappings().first()

    @staticmethod
    def get_movement_details(movement_id):
        sql = text("""
            SELECT 
                md.id,
                md.movement_id,
                md.product_id,
                md.quantity,
                md.received_quantity,
                md.missing_quantity,
                md.lot_number,
                md.expiration_date,
                p.name AS product_name,
                p.sku,
                p.unit_of_measure
            FROM movement_details md
            INNER JOIN products p ON md.product_id = p.id
            WHERE md.movement_id = :movement_id
            ORDER BY md.id ASC
        """)
        return db.session.execute(sql, {"movement_id": movement_id}).fetchall()

    @staticmethod
    def update_detail_quantities(detail_id, received_quantity, missing_quantity):
        sql = text("""
            UPDATE movement_details
            SET 
                received_quantity = :received_quantity,
                missing_quantity = :missing_quantity
            WHERE id = :detail_id
        """)
        db.session.execute(sql, {
            "detail_id": detail_id,
            "received_quantity": received_quantity,
            "missing_quantity": missing_quantity
        })

    @staticmethod
    def get_or_create_inventory(location_id, product_id):
        select_sql = text("""
            SELECT id, location_id, product_id, current_quantity, min_stock, transit_quantity
            FROM inventory
            WHERE location_id = :location_id AND product_id = :product_id
            FOR UPDATE
        """)
        inv = db.session.execute(select_sql, {
            "location_id": location_id,
            "product_id": product_id
        }).mappings().first()

        if not inv:
            insert_sql = text("""
                INSERT INTO inventory (location_id, product_id, current_quantity, min_stock, transit_quantity)
                VALUES (:location_id, :product_id, 0.00, 20.00, 0.00)
                RETURNING id, location_id, product_id, current_quantity, min_stock, transit_quantity
            """)
            inv = db.session.execute(insert_sql, {
                "location_id": location_id,
                "product_id": product_id
            }).mappings().first()

        return inv

    @staticmethod
    def update_origin_transit(location_id, product_id, decrement_transit):
        sql = text("""
            UPDATE inventory
            SET transit_quantity = GREATEST(0.00, transit_quantity - :decrement_transit)
            WHERE location_id = :location_id AND product_id = :product_id
        """)
        db.session.execute(sql, {
            "location_id": location_id,
            "product_id": product_id,
            "decrement_transit": decrement_transit
        })

    @staticmethod
    def increment_destination_stock(location_id, product_id, increment_qty):
        sql = text("""
            UPDATE inventory
            SET current_quantity = current_quantity + :increment_qty
            WHERE location_id = :location_id AND product_id = :product_id
        """)
        db.session.execute(sql, {
            "location_id": location_id,
            "product_id": product_id,
            "increment_qty": increment_qty
        })

    @staticmethod
    def finalize_movement(movement_id, status, received_by_id):
        sql = text("""
            UPDATE movements
            SET 
                status = :status,
                received_by_id = :received_by_id
            WHERE id = :movement_id
        """)
        db.session.execute(sql, {
            "movement_id": movement_id,
            "status": status,
            "received_by_id": received_by_id
        })

    @staticmethod
    def insert_audit_log(audit_data):
        sql = text("""
            INSERT INTO audit_logs (
                affected_table, action, severity, user_id, timestamp, changed_data, location_id
            )
            VALUES (
                :affected_table, :action, :severity, :user_id, :timestamp, CAST(:changed_data AS jsonb), :location_id
            )
        """)
        db.session.execute(sql, audit_data)