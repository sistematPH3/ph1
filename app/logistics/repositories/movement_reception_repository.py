from decimal import Decimal
from datetime import datetime
from threading import Lock
from sqlalchemy import text
from app import db


# Candado en proceso que serializa "buscar + crear" en get_or_create_inventory.
# Sin índice único en inventory(location_id, product_id), dos peticiones
# concurrentes podían ver "no existe" y ambas insertar la misma fila (doble
# asiento en los UPDATEs sin filtro de id). Con un solo worker/proceso, el Lock
# hace atómica la creación sin tocar el esquema de la BD.
_inventory_lock = Lock()


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
                m.return_of_dispute_id,
                loc_orig.name AS origin_name,
                loc_dest.name AS destination_name
            FROM movements m
            INNER JOIN locations loc_orig ON m.origin_location_id = loc_orig.id
            INNER JOIN locations loc_dest ON m.destination_location_id = loc_dest.id
            WHERE m.id = :movement_id
            FOR UPDATE OF m
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
    def get_outstanding_dispatch_debit(movement_id, product_id, lot_number):
        """Saldo pendiente de recuperar de un despacho, contrastado por renglón.

        Para una devolución (RETORNO_EMERGENCIA) se mira el despacho original
        (return_of_dispute_id): por cada renglón del movimiento original con el
        mismo producto y lote se suma 'despachado - recibido-conforme'. Solo ese
        saldo es lo que el origen puede volver a acreditarse al recibir el retorno.

        Un insumo erróneo (fuera de guía) nunca aparece en el despacho original:
        su saldo es 0.00 y, por tanto, NO debe acreditarse de vuelta (evita el
        doble asiento / stock fantasma al recibir el retorno).

        Si el retorno y su despacho original no usan lote (S/L: lot_number NULL),
        el contraste se hace por producto: la bandeja de arbitraje copia el lote
        del renglón original al de la devolución (ver movement_dispute_service),
        así que un detalle sin lote solo puede emparejarse con otro sin lote.
        """
        lot = str(lot_number).strip() if lot_number else None
        if not movement_id or not product_id:
            return Decimal("0.00")
        if lot:
            sql = text("""
                SELECT quantity, received_quantity
                FROM movement_details
                WHERE movement_id = :movement_id
                  AND product_id = :product_id
                  AND LOWER(TRIM(lot_number)) = LOWER(TRIM(:lot_number))
            """)
        else:
            sql = text("""
                SELECT quantity, received_quantity
                FROM movement_details
                WHERE movement_id = :movement_id
                  AND product_id = :product_id
                  AND (lot_number IS NULL OR TRIM(lot_number) = '')
            """)
        rows = db.session.execute(sql, {
            "movement_id": movement_id,
            "product_id": product_id,
            "lot_number": lot
        }).fetchall()
        total = Decimal("0.00")
        for quantity, received_quantity in rows:
            dispatched = Decimal(str(quantity or 0))
            received = Decimal(str(received_quantity or 0))
            # Saldo que el origen tiene derecho a recuperar al recibir una
            # devolución: tanto el faltante (despachado - recibido) que nunca
            # llegó, como el SOBRANTE (recibido - despachado) que el origen
            # debitó de su inventario en resolve_dispute (extra_units) y que
            # regresa físicamente vía el retorno. Con el flujo viejo el origen
            # solo debitaba la guía, por lo que un sobrante daba 0 y el retorno
            # nunca se acreditaba de vuelta (el inventario quedaba corto).
            total += max(dispatched - received, Decimal("0.00")) \
                   + max(received - dispatched, Decimal("0.00"))
        return total

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
        with _inventory_lock:
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

    @staticmethod
    def get_expiration_for_lot(product_id, lot_number):
        """Busca la fecha de vencimiento de un lote de un producto en el histórico.

        El "lote físico real" que registra el muelle (cuando no coincide con la guía)
        suele corresponder a un lote que ya circuló por almacén/compras, de modo que su
        fecha de vencimiento ya está registrada. Se consulta primero el movimiento más
        reciente que usó ese lote y, si no aparece, se busca en las compras.

        Devuelve la fecha de vencimiento (str 'YYYY-MM-DD') o None.
        """
        if not lot_number or not str(lot_number).strip():
            return None

        lot = str(lot_number).strip()

        sql = text("""
            SELECT md.expiration_date
            FROM movement_details md
            WHERE md.product_id = :product_id
              AND md.lot_number = :lot_number
              AND md.expiration_date IS NOT NULL
            ORDER BY md.id DESC
            LIMIT 1
        """)
        row = db.session.execute(sql, {
            "product_id": product_id,
            "lot_number": lot
        }).first()

        if row and row[0]:
            return row[0].strftime('%Y-%m-%d')

        sql2 = text("""
            SELECT pd.expiration_date
            FROM purchase_details pd
            WHERE pd.product_id = :product_id
              AND pd.lot_number = :lot_number
              AND pd.expiration_date IS NOT NULL
            ORDER BY pd.id DESC
            LIMIT 1
        """)
        row2 = db.session.execute(sql2, {
            "product_id": product_id,
            "lot_number": lot
        }).first()

        if row2 and row2[0]:
            return row2[0].strftime('%Y-%m-%d')

        return None

    @staticmethod
    def lot_exists(product_id, lot_number):
        """Indica si un serial/lote ya existe en la base de datos para un producto.

        Se busca en el histórico de movimientos y de compras. No importa si el lote
        tiene o no vencimiento registrado: la sola presencia en la BD indica que el
        serial ya circuló por depósito/compras y, por tanto, "existe".
        """
        if not product_id or not lot_number or not str(lot_number).strip():
            return False

        lot = str(lot_number).strip()

        sql = text("""
            SELECT 1
            FROM movement_details
            WHERE product_id = :product_id AND lot_number = :lot_number
            LIMIT 1
        """)
        row = db.session.execute(sql, {
            "product_id": product_id,
            "lot_number": lot
        }).first()
        if row:
            return True

        sql2 = text("""
            SELECT 1
            FROM purchase_details
            WHERE product_id = :product_id AND lot_number = :lot_number
            LIMIT 1
        """)
        row2 = db.session.execute(sql2, {
            "product_id": product_id,
            "lot_number": lot
        }).first()
        return bool(row2)
