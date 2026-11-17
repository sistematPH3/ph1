import json

from sqlalchemy import func, or_, text

from app.models.inventory_model import Inventory, db
from app.models.logistics_model import (
    Location,
    Movement,
    MovementDetail,
    Purchase,
    PurchaseDetail,
)
from app.models.waste_model import Waste, WasteDetail
from app.models.security_model import User, user_locations

BASE_CONSUMPTION_ACTIONS = ('GASTO_COCINA', 'CONSUMO_COCINA')
CONSUMPTION_LIKE_PATTERNS = ('%GASTO_COCINA%', '%CONSUMO_COCINA%')
ADJUSTMENT_KEYWORDS = ('%AJUSTE%', '%REVERSION%', '%ACTIVACION%')
# Prefijos de acción de los movimientos compensatorios reales generados por el
# módulo (AJUSTE_GASTO_COCINA, REVERSION_GASTO_COCINA, ACTIVACION_GASTO_COCINA).
ADJUSTMENT_ACTION_PREFIXES = ('AJUSTE_', 'REVERSION_', 'ACTIVACION_')
ADJUSTMENT_PREFIXES = tuple(f'{p}%' for p in ADJUSTMENT_ACTION_PREFIXES)

# Los gastos de cocina pertenecen únicamente a sedes operativas. El Almacén
# Central (id 1, creado por el seeder) nunca origina gastos de cocina y tampoco
# debe aparecer en filtros ni conteos de este módulo. Los registros con sede
# nula son datos heredados sin trazabilidad y quedan fuera por el mismo motivo.
CENTRAL_WAREHOUSE_ID = 1


class KitchenExpenseAuditRepository:

    @staticmethod
    def get_user_allowed_locations(user_id):
        rows = db.session.query(user_locations.c.location_id).filter(
            user_locations.c.user_id == user_id
        ).all()
        return [row[0] for row in rows]

    @staticmethod
    def get_all_locations():
        """Sedes operativas: nunca el Almacén Central."""
        return Location.query.filter(
            Location.is_active == True,  # noqa: E712
            Location.id != CENTRAL_WAREHOUSE_ID,
        ).order_by(Location.name).all()

    @staticmethod
    def _operational_locations_only(query, audit):
        """Restringe cualquier consulta de gastos de cocina a sedes operativas."""
        return query.filter(
            audit.c.location_id.isnot(None),
            audit.c.location_id != CENTRAL_WAREHOUSE_ID,
        )

    @staticmethod
    def _scope_query(query, audit, allowed_locations, location_id_filter):
        query = KitchenExpenseAuditRepository._operational_locations_only(query, audit)

        if allowed_locations is not None:
            if not allowed_locations:
                return None
            # El Almacén Central no forma parte del alcance de gastos de cocina.
            operative_allowed = [
                loc_id for loc_id in allowed_locations
                if loc_id is not None and loc_id != CENTRAL_WAREHOUSE_ID
            ]
            if not operative_allowed:
                return None
            query = query.filter(audit.c.location_id.in_(operative_allowed))

        if location_id_filter is not None and location_id_filter != '':
            query = query.filter(audit.c.location_id == int(location_id_filter))
        return query

    @staticmethod
    def get_consumption_logs(allowed_locations=None, location_id_filter=None,
                             severity_filter=None, start_date=None, end_date=None,
                             action_mode='base'):
        """
        Registros de gastos de cocina desde audit_logs.
        action_mode:
          - 'base'      -> solo los consumos originales (GASTO_COCINA/CONSUMO_COCINA)
          - 'adjustments' -> solo los movimientos compensatorios (AJUSTE_/REVERSION_/ACTIVACION_)
          - 'all'       -> todos los relacionados con gastos de cocina
        """
        audit = db.Model.metadata.tables['audit_logs']

        query = db.session.query(
            audit,
            Location.name.label('location_name'),
            User.name.label('user_name'),
        ).outerjoin(
            Location, audit.c.location_id == Location.id
        ).outerjoin(
            User, audit.c.user_id == User.id
        )

        consumption_filter = or_(
            audit.c.action.op('ILIKE')(p) for p in CONSUMPTION_LIKE_PATTERNS
        )
        if action_mode == 'adjustments':
            # La pestaña de Ajustes es exclusiva de movimientos compensatorios:
            # se exige prefijo de compensación y se excluye explícitamente
            # cualquier acción de consumo original. Un GASTO_COCINA puro no
            # puede colarse jamás, ni siquiera si su texto contiene 'AJUSTE'.
            adjustments_filter = or_(
                audit.c.action.op('ILIKE')(p) for p in ADJUSTMENT_PREFIXES
            )
            query = query.filter(
                adjustments_filter,
                consumption_filter,
                audit.c.action.notin_(BASE_CONSUMPTION_ACTIONS),
            )
        elif action_mode == 'base':
            query = query.filter(audit.c.action.in_(BASE_CONSUMPTION_ACTIONS))
        else:
            query = query.filter(consumption_filter)

        query = KitchenExpenseAuditRepository._scope_query(
            query, audit, allowed_locations, location_id_filter
        )
        if query is None:
            return []

        if severity_filter:
            query = query.filter(audit.c.severity == severity_filter)
        if start_date:
            query = query.filter(audit.c.timestamp >= f"{start_date} 00:00:00")
        if end_date:
            query = query.filter(audit.c.timestamp <= f"{end_date} 23:59:59")

        query = query.order_by(audit.c.timestamp.desc())
        return query.all()

    @staticmethod
    def get_inventory_frozen_map(location_ids, product_ids):
        """Stock congelado actual (tránsito + reservado) por (sede, producto),
        para convertir los stock físicos históricos en 'disponibles' al visualizar."""
        location_ids = [i for i in (location_ids or []) if i is not None]
        product_ids = [p for p in (product_ids or []) if p is not None]
        if not location_ids or not product_ids:
            return {}
        rows = db.session.query(
            Inventory.location_id,
            Inventory.product_id,
            (func.coalesce(Inventory.transit_quantity, 0) + func.coalesce(Inventory.reserved_quantity, 0)).label('frozen'),
        ).filter(
            Inventory.location_id.in_(location_ids),
            Inventory.product_id.in_(product_ids),
        ).all()
        return {(r.location_id, r.product_id): float(r.frozen or 0) for r in rows}

    @staticmethod
    def get_current_available_map(location_ids, product_ids):
        """Disponible actual (físico - reservado) por (sede, producto),
        tal como se muestra en el inventario en este momento. El tránsito ya
        está descontado de current_quantity al despachar."""
        location_ids = [i for i in (location_ids or []) if i is not None]
        product_ids = [p for p in (product_ids or []) if p is not None]
        if not location_ids or not product_ids:
            return {}
        rows = db.session.query(
            Inventory.location_id,
            Inventory.product_id,
            (func.coalesce(Inventory.current_quantity, 0) -
             func.coalesce(Inventory.reserved_quantity, 0)).label('available'),
        ).filter(
            Inventory.location_id.in_(location_ids),
            Inventory.product_id.in_(product_ids),
        ).all()
        return {(r.location_id, r.product_id): float(r.available or 0) for r in rows}

    @staticmethod
    def get_consumption_logs_date_range(allowed_locations=None, location_id_filter=None):
        """Rango (min, max) de fechas con consumos registrados, para acotar el calendario."""
        audit = db.Model.metadata.tables['audit_logs']
        query = db.session.query(
            db.func.min(audit.c.timestamp),
            db.func.max(audit.c.timestamp)
        ).filter(
            audit.c.action.in_(BASE_CONSUMPTION_ACTIONS),
            audit.c.timestamp.isnot(None),
        )

        query = KitchenExpenseAuditRepository._scope_query(
            query, audit, allowed_locations, location_id_filter
        )
        if query is None:
            return None, None
        return query.first()

    @staticmethod
    def get_audit_log_by_id(log_id):
        audit = db.Model.metadata.tables['audit_logs']
        return db.session.query(audit).filter(audit.c.id == log_id).first()

    @staticmethod
    def get_current_stock(location_id, product_id):
        result = db.session.execute(text(
            "SELECT current_quantity FROM inventory "
            "WHERE location_id = :loc_id AND product_id = :prod_id"
        ), {'loc_id': location_id, 'prod_id': product_id}).fetchone()
        return result[0] if result else "0.00"

    @staticmethod
    def get_inventory_state(location_id, product_id):
        result = db.session.execute(text(
            "SELECT current_quantity, transit_quantity, reserved_quantity FROM inventory "
            "WHERE location_id = :loc_id AND product_id = :prod_id"
        ), {'loc_id': location_id, 'prod_id': product_id}).fetchone()
        if not result:
            return {'current_quantity': '0.00', 'transit_quantity': '0.00', 'reserved_quantity': '0.00'}
        return {
            'current_quantity': result[0],
            'transit_quantity': result[1],
            'reserved_quantity': result[2],
        }

    @staticmethod
    def validate_return_lot(lot_number, product_id, location_id):
        """Valida el lote de origen de una devolución de stock (edición a la baja
        o anulación) con TRES condiciones obligatorias:

        1. Existencia real: el lote existe (o existió) en compras, traslados o
           mermas registradas del sistema.
        2. Correlación de producto: ese lote pertenece al insumo que se ajusta;
           nunca se acepta un lote de otro producto con el mismo número.
        3. Pertenencia a la sede: el lote fue recibido/despachado o mermado en
           la misma sede donde se originó el gasto.

        Se valida antes de cualquier UPDATE de stock para no corromper la
        trazabilidad de vencimientos ni el consumo FIFO.
        """
        raw = str(lot_number).strip() if lot_number is not None else ''
        if not raw or raw.upper() in ('N/A', 'NONE', 'SIN LOTE'):
            return {
                'is_valid': False,
                'message': 'Debe indicar el lote real de origen del insumo para devolver stock.',
            }
        try:
            product_id = int(product_id)
            location_id = int(location_id)
        except (TypeError, ValueError):
            return {
                'is_valid': False,
                'message': 'No se pudo determinar el insumo o la sede del gasto a devolver.',
            }

        lot_key = raw.upper()
        lot_expr = func.upper(func.trim(PurchaseDetail.lot_number))

        # 1) Compras completadas (los lotes nacen en el Almacén Central).
        purchase_rows = db.session.query(PurchaseDetail.product_id).join(
            Purchase, PurchaseDetail.purchase_id == Purchase.id
        ).filter(
            lot_expr == lot_key,
            func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
            PurchaseDetail.product_id.isnot(None),
        ).all()

        # 2) Traslados válidos: el lote estuvo en la sede como destino u origen.
        movement_rows = db.session.query(
            MovementDetail.product_id,
            Movement.destination_location_id,
            Movement.origin_location_id,
        ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
            func.upper(func.trim(MovementDetail.lot_number)) == lot_key,
            func.upper(Movement.status).in_([
                'COMPLETED', 'COMPLETADO', 'NOVEDAD_FALTANTE',
                'CERRADO_POR_ADMIN', 'CERRADO_CON_PERDIDA',
            ]),
            MovementDetail.product_id.isnot(None),
        ).all()

        # 3) Mermas registradas en la sede (incluye lote ya agotado).
        waste_rows = db.session.query(
            WasteDetail.product_id,
            Waste.location_id,
        ).join(Waste, Waste.id == WasteDetail.waste_id).filter(
            func.upper(func.trim(WasteDetail.lot_number)) == lot_key,
            Waste.cancelled_at.is_(None),
            WasteDetail.product_id.isnot(None),
        ).all()

        known_product_ids = (
            {row[0] for row in purchase_rows}
            | {row[0] for row in movement_rows}
            | {row[0] for row in waste_rows}
        )

        if not known_product_ids:
            return {
                'is_valid': False,
                'message': (
                    f"El lote '{raw}' no existe en los registros del sistema. "
                    'Verifique el número de lote real del insumo.'
                ),
            }

        if product_id not in known_product_ids:
            return {
                'is_valid': False,
                'message': (
                    f"El lote '{raw}' pertenece a otro insumo y no puede usarse "
                    'para devolver stock del gasto seleccionado.'
                ),
            }

        belongs_to_location = (
            (location_id == CENTRAL_WAREHOUSE_ID and bool(purchase_rows))
            or any(
                location_id in (row[1], row[2])
                for row in movement_rows if row[0] == product_id
            )
            or any(
                row[1] == location_id
                for row in waste_rows if row[0] == product_id
            )
        )
        if not belongs_to_location:
            return {
                'is_valid': False,
                'message': (
                    f"El lote '{raw}' no está asociado a la sede de origen del "
                    'gasto. Use un lote que haya ingresado o se haya consumido '
                    'en esa sede.'
                ),
            }

        return {'is_valid': True, 'message': '', 'lot_number': raw}

    @staticmethod
    def register_consumption_adjustment(user_id, location_id, action_type, severity,
                                        product_id, product_name, prev_qty, new_qty,
                                        qty_changed, prev_physical_qty, new_physical_qty,
                                        original_quantity, edited_quantity,
                                        notes, original_log_id=None,
                                        new_original_severity=None, lot_number=None):
        """Registra el movimiento compensatorio de la auditoría y ajusta el stock físico.
        prev_qty/new_qty = stock disponible antes/después (current - reserved;
        el tránsito ya está descontado de current_quantity);
        prev_physical_qty/new_physical_qty = stock físico para el UPDATE;
        original_quantity/edited_quantity = cantidad de gasto original y corregida."""
        result = db.session.execute(text(
            "INSERT INTO audit_logs (user_id, location_id, action, severity, timestamp, changed_data) "
            "VALUES (:user_id, :location_id, :action, :severity, NOW(), :changed_data) RETURNING id"
        ), {
            'user_id': user_id,
            'location_id': location_id,
            'action': action_type,
            'severity': severity,
            'changed_data': json.dumps({
                'product_id': product_id,
                'product_name': product_name,
                'previous_quantity': prev_qty,
                'new_quantity': new_qty,
                'quantity_changed': qty_changed,
                'previous_physical_quantity': prev_physical_qty,
                'new_physical_quantity': new_physical_qty,
                'original_quantity': original_quantity,
                'edited_quantity': edited_quantity,
                **({'target_log_id': original_log_id} if original_log_id else {}),
                'notes': notes,
                **({'lot_number': str(lot_number).strip()} if lot_number else {}),
            }),
        })
        adjustment_log_id = result.scalar()

        db.session.execute(text(
            "UPDATE inventory SET current_quantity = :new_physical_qty "
            "WHERE location_id = :loc_id AND product_id = :prod_id"
        ), {
            'new_physical_qty': new_physical_qty,
            'loc_id': location_id,
            'prod_id': product_id,
        })

        if original_log_id:
            from app.models.waste_model import AuditLog as _AuditLog
            target = db.session.get(_AuditLog, original_log_id)
            if target is not None:
                d = target.changed_data or {}
                if isinstance(d, str):
                    try:
                        d = json.loads(d)
                    except (json.JSONDecodeError, TypeError):
                        d = {}
                if not isinstance(d, dict):
                    d = {}
                d.update({
                    'adjustment_log_id': adjustment_log_id,
                    'original_quantity': original_quantity,
                    'edited_quantity': edited_quantity,
                })
                target.changed_data = d
                if new_original_severity:
                    target.severity = new_original_severity

        db.session.commit()