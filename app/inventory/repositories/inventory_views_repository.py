import json
import logging
from sqlalchemy import func
from app import db
from app.models import Inventory, Product, Location, user_locations
from app.models.logistics_model import Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import AuditLog

logger = logging.getLogger(__name__)


class InventoryViewRepository:
    
    @staticmethod
    def get_inventory_by_location(location_id, search_term=None):
        return InventoryViewRepository.get_inventory_by_locations(
            [location_id], search_term
        )

    @staticmethod
    def get_inventory_by_locations(location_ids, search_term=None):
        """Inventario consolidado de varias sedes en UNA sola consulta.

        Se usa `location_id.in_(...)` para que un usuario con varias sedes
        asignadas vea todas sus existencias juntas en lugar de una sola sede.
        """
        ids = []
        for location_id in location_ids or []:
            try:
                ids.append(int(location_id))
            except (TypeError, ValueError):
                continue

        if not ids:
            return []

        query = Inventory.query.join(Product).join(Location).filter(
            Inventory.location_id.in_(ids)
        ).order_by(Location.name, Product.name)

        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )

        return query.all()

    @staticmethod
    def get_all_inventory(search_term=None):
        query = Inventory.query.join(Product).join(Location)
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_user_assigned_locations(user_id):
        return Location.query.join(
            user_locations, 
            Location.id == user_locations.c.location_id
        ).filter(user_locations.c.user_id == user_id).all()

    @staticmethod
    def get_all_active_locations():
        return Location.query.filter_by(is_active=True).all()

    @staticmethod
    def get_low_stock_counts_by_location():
        results = db.session.query(
            Location.id,
            Location.name,
            func.count(Inventory.id).label('low_stock_count')
        ).join(Inventory, Location.id == Inventory.location_id)\
         .join(Product, Inventory.product_id == Product.id)\
         .filter(
            Location.is_active == True,
            Product.is_active == True,
            Inventory.current_quantity > 0,
            # El tránsito ya está descontado de current_quantity al despachar.
            (Inventory.current_quantity
             - func.coalesce(Inventory.reserved_quantity, 0)) <= Inventory.min_stock
        ).group_by(Location.id, Location.name).all()

        return [
            {
                'location_id': r.id,
                'location_name': r.name,
                'count': r.low_stock_count
            } for r in results if r.low_stock_count > 0
        ]

    @staticmethod
    def _pending_dispute_statuses():
        """Estados de movimiento que representan una disputa aún abierta.

        Se importa dentro del método para evitar ciclos de importación entre el
        módulo de inventario y el de logística.
        """
        from app.logistics.repositories.movement_dispute_repository import (
            MovementDisputeRepository,
        )
        return MovementDisputeRepository.PENDING_DISPUTE_STATUSES

    @staticmethod
    def _held_units_expr():
        """Unidades resguardadas en el ORIGEN por una disputa abierta.

        No son solo faltantes: un sobrante pendiente de arbitraje también salió
        físicamente del origen y quedó congelado en su `transit_quantity` (ver
        `debit_origin_surplus`). Si solo se sumara `missing_quantity`, esas
        unidades se exhibirían como tránsito genérico en vez de "en disputa".
        """
        return (
            func.coalesce(MovementDetail.missing_quantity, 0)
            + func.greatest(
                func.coalesce(MovementDetail.received_quantity, 0)
                - MovementDetail.quantity,
                0,
            )
        )

    @staticmethod
    def get_disputed_qty_by_location():
        """Unidades en disputa por (sede origen, producto): faltante + sobrante.

        Mientras una recepción con novedad no se resuelve, tanto el faltante
        (nunca llegó) como el sobrante (llegó de más y salió físicamente del
        origen) quedan resguardados en el ORIGEN. Se calculan desde los
        movimientos abiertos para que sean visibles incluso en registros viejos
        donde el tránsito ya se había liberado.
        """
        statuses = InventoryViewRepository._pending_dispute_statuses()
        rows = db.session.query(
            Movement.origin_location_id.label('location_id'),
            MovementDetail.product_id.label('product_id'),
            func.sum(InventoryViewRepository._held_units_expr()).label('disputed')
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.status.in_(statuses),
            InventoryViewRepository._held_units_expr() > 0,
        ).group_by(
            Movement.origin_location_id, MovementDetail.product_id
        ).all()

        return {
            (r.location_id, r.product_id): float(r.disputed or 0.0)
            for r in rows
        }

    @staticmethod
    def get_disputed_qty_by_lot(location_id, product_id):
        """Unidades en disputa (faltante + sobrante) por lote de origen."""
        statuses = InventoryViewRepository._pending_dispute_statuses()
        rows = db.session.query(
            MovementDetail.lot_number.label('lot_number'),
            func.sum(InventoryViewRepository._held_units_expr()).label('disputed')
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.origin_location_id == int(location_id),
            Movement.status.in_(statuses),
            MovementDetail.product_id == int(product_id),
            MovementDetail.lot_number.isnot(None),
            MovementDetail.lot_number != '',
            InventoryViewRepository._held_units_expr() > 0,
        ).group_by(MovementDetail.lot_number).all()

        return {
            str(r.lot_number).strip(): float(r.disputed or 0.0)
            for r in rows if r.lot_number
        }

    @staticmethod
    def get_return_transit_by_location():
        """Devoluciones ya despachadas por (sede origen, producto).

        El traslado de retorno (`RETORNO_EMERGENCIA`) incrementa el tránsito de
        la sede que devuelve para que la recepción en Central pueda liberarlo,
        pero NO debe mostrarse como tránsito genérico: son unidades que ya no
        pertenecen a esa sede y están en camino al Almacén Central.
        """
        rows = db.session.query(
            Movement.origin_location_id.label('location_id'),
            MovementDetail.product_id.label('product_id'),
            func.sum(MovementDetail.quantity).label('qty'),
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.type == 'RETORNO_EMERGENCIA',
            Movement.status == 'EN_TRANSITO',
        ).group_by(
            Movement.origin_location_id, MovementDetail.product_id
        ).all()

        return {
            (r.location_id, r.product_id): float(r.qty or 0.0)
            for r in rows
        }

    @staticmethod
    def get_incoming_return_qty_by_location():
        """Devoluciones pendientes de recepción por (sede destino, producto).

        Permite que el Almacén Central exhiba esas unidades como retenidas en
        muelle (aún no disponibles) mientras el traslado siga EN_TRANSITO.
        """
        rows = db.session.query(
            Movement.destination_location_id.label('location_id'),
            MovementDetail.product_id.label('product_id'),
            func.sum(MovementDetail.quantity).label('qty'),
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.type == 'RETORNO_EMERGENCIA',
            Movement.status == 'EN_TRANSITO',
        ).group_by(
            Movement.destination_location_id, MovementDetail.product_id
        ).all()

        return {
            (r.location_id, r.product_id): float(r.qty or 0.0)
            for r in rows
        }

    @staticmethod
    def get_disputed_lots(location_id, product_id):
        """Disputa abierta por lote (faltante + sobrante) en el origen.

        Devuelve cantidad y fecha de vencimiento para poder pintar en el
        detalle de lotes incluso partidas que no tienen entrada registrada
        (por ejemplo, un sobrante de una guía cuyo lote no está en compras).
        """
        statuses = InventoryViewRepository._pending_dispute_statuses()
        rows = db.session.query(
            MovementDetail.lot_number.label('lot_number'),
            func.max(MovementDetail.expiration_date).label('expiration_date'),
            func.sum(InventoryViewRepository._held_units_expr()).label('qty'),
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.origin_location_id == int(location_id),
            Movement.status.in_(statuses),
            MovementDetail.product_id == int(product_id),
            MovementDetail.lot_number.isnot(None),
            MovementDetail.lot_number != '',
            InventoryViewRepository._held_units_expr() > 0,
        ).group_by(MovementDetail.lot_number).all()

        return {
            str(r.lot_number).strip(): {
                'quantity': float(r.qty or 0.0),
                'expiration_date': r.expiration_date,
            }
            for r in rows if r.lot_number
        }

    @staticmethod
    def get_return_transit_lots(location_id, product_id):
        """Devoluciones al Central ya despachadas, desglosadas por lote."""
        rows = db.session.query(
            MovementDetail.lot_number.label('lot_number'),
            func.max(MovementDetail.expiration_date).label('expiration_date'),
            func.sum(MovementDetail.quantity).label('qty'),
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.origin_location_id == int(location_id),
            Movement.type == 'RETORNO_EMERGENCIA',
            Movement.status == 'EN_TRANSITO',
            MovementDetail.product_id == int(product_id),
            MovementDetail.lot_number.isnot(None),
            MovementDetail.lot_number != '',
        ).group_by(MovementDetail.lot_number).all()

        return {
            str(r.lot_number).strip(): {
                'quantity': float(r.qty or 0.0),
                'expiration_date': r.expiration_date,
            }
            for r in rows if r.lot_number
        }

    @staticmethod
    def get_incoming_return_lots(location_id, product_id):
        """Devoluciones en camino a esta sede, desglosadas por lote.

        Se muestran como retenidas por recibir hasta que se registre la
        recepción física en muelle.
        """
        rows = db.session.query(
            MovementDetail.lot_number.label('lot_number'),
            func.max(MovementDetail.expiration_date).label('expiration_date'),
            func.sum(MovementDetail.quantity).label('qty'),
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.destination_location_id == int(location_id),
            Movement.type == 'RETORNO_EMERGENCIA',
            Movement.status == 'EN_TRANSITO',
            MovementDetail.product_id == int(product_id),
            MovementDetail.lot_number.isnot(None),
            MovementDetail.lot_number != '',
        ).group_by(MovementDetail.lot_number).all()

        return {
            str(r.lot_number).strip(): {
                'quantity': float(r.qty or 0.0),
                'expiration_date': r.expiration_date,
            }
            for r in rows if r.lot_number
        }

    @staticmethod
    def get_product_lots_by_location(location_id, product_id):
        """Saldo por lote de una sede usando la MISMA fuente única de verdad que
        el resto del sistema (_compute_lot_availability): consumos netos
        (editados/anulados), mermas por estado real y traslados. Evita que el
        detalle de lotes diverja del inventario general de la sede.
        """
        from app.inventory.services.lot_availability_service import (
            _compute_lot_availability,
        )
        loc_id = int(location_id)
        prod_id = int(product_id)
        avail = _compute_lot_availability(loc_id, [prod_id])
        lots = []
        for (pid, lot_num), data in avail.items():
            if pid != prod_id or data['availability'] <= 0.001:
                continue
            exp = data['expiration_date']
            lots.append({
                'lot_number': lot_num,
                'expiration_date': exp.strftime('%d/%m/%Y') if exp else 'Sin vencimiento',
                'quantity': round(float(data['availability']), 2),
                'exp_date_raw': exp,
            })
        lots.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))
        for l in lots:
            l.pop('exp_date_raw', None)
        return lots