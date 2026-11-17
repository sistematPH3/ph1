import json
import logging
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, or_, case
from app import db
from app.models import Inventory, Movement, MovementDetail, Purchase, PurchaseDetail, AuditLog
from app.models.waste_model import Waste, WasteDetail
from app.inventory.repositories.inventory_views_repository import InventoryViewRepository
from app.inventory.services.lot_availability_service import net_consumption_quantity

logger = logging.getLogger(__name__)


class InventoryViewService:

    @staticmethod
    def _attach_inventory_state_quantities(inventory_data):
        """Adjunta a cada registro las cantidades de inventario dual.

        - `disputed_quantity`: faltante + sobrante de recepciones aún sin
          arbitrar, resguardados en el origen.
        - `return_transit_quantity`: unidades ya despachadas en un traslado de
          retorno hacia Central; no son tránsito genérico de la sede.
        - `retained_incoming_quantity`: retornos aún EN_TRANSITO cuyo destino es
          esta sede (Central), retenidos en muelle a la espera de recepción.

        Todas se exponen como Decimal para no mezclar tipos con
        `transit_quantity` y romper las restas de la vista.
        """
        if not inventory_data:
            return inventory_data
        disputed_map = InventoryViewRepository.get_disputed_qty_by_location()
        return_transit_map = InventoryViewRepository.get_return_transit_by_location()
        incoming_map = InventoryViewRepository.get_incoming_return_qty_by_location()
        for item in inventory_data:
            key = (item.location_id, item.product_id)
            item.disputed_quantity = InventoryViewService._to_decimal(
                disputed_map.get(key, 0)
            )
            item.return_transit_quantity = InventoryViewService._to_decimal(
                return_transit_map.get(key, 0)
            )
            item.retained_incoming_quantity = InventoryViewService._to_decimal(
                incoming_map.get(key, 0)
            )
        return inventory_data

    @staticmethod
    def _to_decimal(value):
        """Convierte de forma segura un valor numérico (float, str, JSON) a Decimal."""
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal('0.00')

    @staticmethod
    def get_inventory_for_user(current_user, filter_params):
        search_term = filter_params.get('search_term') or filter_params.get('search')
        selected_location_id = filter_params.get('location_id')

        if selected_location_id and str(selected_location_id).isdigit():
            selected_location_id = int(selected_location_id)

        role_name = current_user.role.name.lower() if (current_user and current_user.role) else ''
        is_admin = 'admin' in role_name or getattr(current_user, 'role_id', None) == 1 or getattr(current_user, 'is_admin', False)

        if is_admin:
            locations_list = InventoryViewRepository.get_all_active_locations()

            if not selected_location_id and locations_list:
                selected_location_id = locations_list[0].id

            if selected_location_id:
                inventory_data = InventoryViewRepository.get_inventory_by_location(selected_location_id, search_term)
            else:
                inventory_data = InventoryViewRepository.get_all_inventory(search_term)

            alerts_summary = InventoryViewRepository.get_low_stock_counts_by_location()
            total_global_alerts = sum(item['count'] for item in alerts_summary)

            InventoryViewService._attach_inventory_state_quantities(inventory_data)

            return {
                'is_admin': True,
                'inventory': inventory_data,
                'available_locations': locations_list,
                'selected_location_id': selected_location_id,
                'alerts_summary': alerts_summary,
                'total_global_alerts': total_global_alerts
            }

        else:
            assigned_locations = InventoryViewRepository.get_user_assigned_locations(current_user.id)

            if assigned_locations:
                user_location_id = assigned_locations[0].id
                inventory_data = InventoryViewRepository.get_inventory_by_location(user_location_id, search_term)
                location_name = assigned_locations[0].name
            else:
                inventory_data = []
                location_name = "Sin Sede Asignada"

            InventoryViewService._attach_inventory_state_quantities(inventory_data)

            return {
                'is_admin': False,
                'inventory': inventory_data,
                'available_locations': assigned_locations,
                'assigned_location_name': location_name,
                'selected_location_id': assigned_locations[0].id if assigned_locations else None
            }

    @staticmethod
    def get_lots_for_product(location_id, product_id):
        loc_id = int(location_id)
        prod_id = int(product_id)

        inventory = db.session.query(Inventory).filter_by(
            location_id=loc_id,
            product_id=prod_id
        ).first()

        total_stock = float(inventory.current_quantity) if inventory else 0.0

        # El tránsito NO se resta: al despachar ya se descontó de
        # current_quantity. Restarlo aquí lo descontaría dos veces.
        reservado_total = (
            float(inventory.reserved_quantity or 0) if inventory else 0.0
        )
        disponible_total = max(0.0, total_stock - reservado_total)

        entradas_lote = {}
        salidas_traslado = {}

        if loc_id == 1:
            # El Central recibe mercancía de dos orígenes: COMPRAS (PurchaseDetail)
            # y RETORNOS/TRASLADOS que vuelven desde las sucursales (MovementDetail
            # con destination_location_id == 1). Ambos suman stock y se despliegan
            # con su lote.
            compras = db.session.query(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date,
                func.sum(PurchaseDetail.quantity).label('total_qty')
            ).join(
                Purchase, PurchaseDetail.purchase_id == Purchase.id
            ).filter(
                func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
                PurchaseDetail.product_id == prod_id,
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).group_by(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date
            ).all()

            for c in compras:
                lot = c.lot_number.strip()
                entradas_lote[lot] = {
                    'expiration_date': c.expiration_date,
                    'total_in': float(c.total_qty or 0.0)
                }

            # Salidas desde el Central: despachos a sucursales.
            # Se descuenta la cantidad física que realmente salió del origen:
            #   - con recepción, lo recibido (cubre faltante y sobrante);
            #   - sin recepción (aún EN_TRANSITO), lo despachado.
            # Usar el mayor (greatest) sobre-descontaba el faltante que nunca
            # salió del Central y descuadraba el detalle de lotes contra el
            # current_quantity real.
            salida_fisica_central = func.coalesce(
                MovementDetail.received_quantity, MovementDetail.quantity
            )
            despachos = db.session.query(
                MovementDetail.lot_number,
                func.sum(salida_fisica_central).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == 1,
                Movement.status.notin_(['CANCELADO', 'CANCELADO_EMISOR', 'ANULADO', 'RECHAZADO']),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None)
            ).group_by(MovementDetail.lot_number).all()

            salidas_traslado = {d.lot_number.strip(): float(d.total_out or 0.0) for d in despachos if d.lot_number}

            # Entradas por RETORNO/TRASLADO que llegan al Central. Se usa la misma
            # lógica de "cantidad efectivamente recibida" que en sucursales para
            # NO sumar de más (evita doble asiento): solo lo realmente recibido
            # (received_quantity), nunca más de lo despachado.
            valid_statuses_central = ['COMPLETED', 'COMPLETADO', 'CERRADO_POR_ADMIN']

            effective_qty_central = case(
                (
                    Movement.status == 'CERRADO_POR_ADMIN',
                    func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity)
                ),
                else_=func.least(
                    func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity),
                    MovementDetail.quantity
                )
            )

            retornos = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date,
                func.sum(effective_qty_central).label('total_qty')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                func.upper(Movement.status).in_(valid_statuses_central),
                Movement.destination_location_id == 1,
                Movement.origin_location_id.isnot(None),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).all()

            for r in retornos:
                lot = r.lot_number.strip()
                if lot in entradas_lote:
                    entradas_lote[lot]['total_in'] += float(r.total_qty or 0.0)
                else:
                    entradas_lote[lot] = {
                        'expiration_date': r.expiration_date,
                        'total_in': float(r.total_qty or 0.0)
                    }

        else:
            valid_statuses = ['COMPLETED', 'COMPLETADO', 'NOVEDAD_FALTANTE', 'CERRADO_POR_ADMIN', 'CERRADO_CON_PERDIDA']

            effective_qty_expr = case(
                (
                    Movement.status == 'CERRADO_POR_ADMIN',
                    func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity)
                ),
                else_=func.least(
                    func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity),
                    MovementDetail.quantity
                )
            )

            movimientos_in = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date,
                func.sum(effective_qty_expr).label('total_qty')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                func.upper(Movement.status).in_(valid_statuses),
                Movement.destination_location_id == loc_id,
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).all()

            for m in movimientos_in:
                lot = m.lot_number.strip()
                entradas_lote[lot] = {
                    'expiration_date': m.expiration_date,
                    'total_in': float(m.total_qty or 0.0)
                }

            # Salidas desde la sucursal. Se descuentan los DESPACHOS que salen
            # hacia otra sede (stock que el destino envía adelante). Los
            # RETORNO_EMERGENCIA (devoluciones al emisor, generadas por el
            # arbitraje) NO se descuentan: devuelven excedente que nunca fue
            # acreditado como conforme en el destino, por lo que restarlo
            # descontaría dos veces el mismo sobrante.
            despachos_sucursal = db.session.query(
                MovementDetail.lot_number,
                # Salida física real: lo recibido si ya hubo recepción (cubre
                # faltante y sobrante); lo despachado si sigue EN_TRANSITO.
                func.sum(func.coalesce(
                    MovementDetail.received_quantity, MovementDetail.quantity
                )).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == loc_id,
                Movement.type != 'RETORNO_EMERGENCIA',
                Movement.status.notin_(['CANCELADO', 'CANCELADO_EMISOR', 'ANULADO', 'RECHAZADO']),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None)
            ).group_by(MovementDetail.lot_number).all()

            salidas_traslado = {d.lot_number.strip(): float(d.total_out or 0.0) for d in despachos_sucursal if d.lot_number}

        # Solo gastos/consumos base. Las mermas se derivan de Waste/WasteDetail
        # (estado real), no de sus auditorías: una merma REVERTIDA devuelve el
        # stock y su audit_log histórico ya no debe descontar el lote.
        audit_consumos = db.session.query(
            AuditLog.changed_data, AuditLog.severity
        ).filter(
            AuditLog.location_id == loc_id,
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA'])
        ).all()

        salidas_consumo = {}
        for c_data, severity in audit_consumos:
            if not c_data:
                continue
            if isinstance(c_data, str):
                try:
                    c_data = json.loads(c_data)
                except Exception as exc:
                    logger.warning(
                        "Registro de auditoría con JSON inválido; se omite la fila: %s",
                        exc,
                    )
                    continue
            if isinstance(c_data, dict):
                p_id = c_data.get('product_id')
                l_num = c_data.get('lot_number')
                if (p_id is None or int(p_id) == prod_id) and l_num and l_num != 'N/A':
                    # Cantidad vigente (editada) o 0 si está anulado: mantiene
                    # sincronizado el lote con el stock general de la sede.
                    qty = net_consumption_quantity(c_data, severity)
                    if qty <= 0:
                        continue
                    l_num_clean = str(l_num).strip()
                    salidas_consumo[l_num_clean] = salidas_consumo.get(l_num_clean, 0.0) + qty

        # Mermas PENDIENTES: la cantidad está congelada (reserved_quantity) y no
        # está disponible para consumo/traslado, así que también se descuenta del
        # lote. Mismo criterio que register_waste_repository.
        salidas_mermas_pendientes = {}
        pendientes_rows = db.session.query(
            WasteDetail.lot_number,
            func.sum(WasteDetail.quantity).label('total_pend')
        ).join(Waste, Waste.id == WasteDetail.waste_id).filter(
            or_(
                Waste.status == 'PENDIENTE',
                (Waste.status == 'APROBADO_PARCIAL') & (WasteDetail.status != 'APROBADO'),
            ),
            Waste.cancelled_at.is_(None),
            Waste.location_id == loc_id,
            WasteDetail.product_id == prod_id,
            WasteDetail.lot_number.isnot(None),
        ).group_by(WasteDetail.lot_number).all()
        for lot, total_pend in pendientes_rows:
            if lot and str(lot).strip() and str(lot).strip() != 'N/A':
                lote_limpio = str(lot).strip()
                salidas_mermas_pendientes[lote_limpio] = float(total_pend or 0.0)

        # Mermas APROBADAS: ya descontaron el stock físico y, si se revierten,
        # su cabecera deja de estar APROBADA, por lo que vuelven a sumar al lote.
        salidas_mermas_aprobadas = {}
        aprobadas_rows = db.session.query(
            WasteDetail.lot_number,
            func.sum(WasteDetail.quantity).label('total_mermado')
        ).join(Waste, Waste.id == WasteDetail.waste_id).filter(
            or_(
                Waste.status == 'APROBADO',
                (Waste.status == 'APROBADO_PARCIAL') & (WasteDetail.status == 'APROBADO'),
            ),
            Waste.cancelled_at.is_(None),
            Waste.location_id == loc_id,
            WasteDetail.product_id == prod_id,
            WasteDetail.lot_number.isnot(None),
        ).group_by(WasteDetail.lot_number).all()
        for lot, total_mermado in aprobadas_rows:
            if lot and str(lot).strip() and str(lot).strip() != 'N/A':
                salidas_mermas_aprobadas[str(lot).strip()] = float(total_mermado or 0.0)

        # Traslados EN_TRANSITO: esa mercancía ya salió físicamente de la sede
        # (despacho pendiente de recepción), así que no se puede tocar. Se resta
        # del disponible (vía salidas_traslado) y además se desglosa como
        # "Congelado/Tránsito" para que el usuario sepa cuánto está en camino.
        salidas_transito = {}
        en_transito_rows = db.session.query(
            MovementDetail.lot_number,
            func.sum(MovementDetail.quantity).label('total_transit')
        ).join(
            Movement, MovementDetail.movement_id == Movement.id
        ).filter(
            Movement.origin_location_id == loc_id,
            Movement.type != 'RETORNO_EMERGENCIA',
            Movement.status == 'EN_TRANSITO',
            MovementDetail.product_id == prod_id,
            MovementDetail.lot_number.isnot(None),
            MovementDetail.lot_number != ''
        ).group_by(MovementDetail.lot_number).all()
        for lot, total_transit in en_transito_rows:
            if lot and str(lot).strip() and str(lot).strip() != 'N/A':
                lote_limpio = str(lot).strip()
                salidas_transito[lote_limpio] = float(total_transit or 0.0)

        # Incidencias por lote. Se consultan por separado de las entradas para
        # que partidas sin recepción conforme (sobrante en disputa, devolución
        # al Central o retorno retenido en muelle) también aparezcan en el
        # detalle, con su fecha de vencimiento y sin mezclarse entre estados.
        disputa_lotes = InventoryViewRepository.get_disputed_lots(loc_id, prod_id)
        retorno_lotes = InventoryViewRepository.get_return_transit_lots(loc_id, prod_id)
        retenido_lotes = InventoryViewRepository.get_incoming_return_lots(loc_id, prod_id)

        salidas_disputa = {lot: d['quantity'] for lot, d in disputa_lotes.items()}
        salidas_retorno = {lot: d['quantity'] for lot, d in retorno_lotes.items()}
        retenido_entrante = {lot: d['quantity'] for lot, d in retenido_lotes.items()}

        lots_raw = []
        lotes = (
            set(entradas_lote)
            | set(salidas_disputa)
            | set(salidas_retorno)
            | set(retenido_entrante)
        )
        for lot_num in lotes:
            data = entradas_lote.get(lot_num)
            total_in = data['total_in'] if data else 0.0

            expiration = data['expiration_date'] if data else None
            if expiration is None:
                for fuente in (disputa_lotes, retorno_lotes, retenido_lotes):
                    if lot_num in fuente:
                        expiration = fuente[lot_num]['expiration_date']
                        break

            total_out_traslados = salidas_traslado.get(lot_num, 0.0)
            total_out_consumos = salidas_consumo.get(lot_num, 0.0)
            total_out_mermas = salidas_mermas_pendientes.get(lot_num, 0.0)
            total_out_mermas_aprobadas = salidas_mermas_aprobadas.get(lot_num, 0.0)
            total_out_transito = salidas_transito.get(lot_num, 0.0)
            total_out_disputa = salidas_disputa.get(lot_num, 0.0)
            total_out_retorno = salidas_retorno.get(lot_num, 0.0)
            total_retenido = retenido_entrante.get(lot_num, 0.0)

            # `total_out_disputa` NO se resta del disponible: `salidas_traslado`
            # ya descuenta la salida física del lote. Restarlo de nuevo ocultaba
            # stock y, en sobrantes, lo descontaba dos veces. La disputa se
            # expone aparte en `frozen_disputed_quantity`.
            disponible = max(0.0, (
                total_in - total_out_traslados - total_out_consumos
                - total_out_mermas - total_out_mermas_aprobadas
            ))

            incidencias = (
                total_out_mermas + total_out_transito + total_out_disputa
                + total_out_retorno + total_retenido
            )
            if disponible > 0.001 or incidencias > 0.001:
                lots_raw.append({
                    'lot_number': lot_num,
                    'expiration_date': expiration.strftime('%Y-%m-%d') if expiration else '',
                    'disponible': disponible,
                    'frozen': total_out_mermas,
                    'transit': total_out_transito,
                    'disputed': total_out_disputa,
                    'return_transit': total_out_retorno,
                    'retained': total_retenido,
                    'initial_quantity': round(float(total_in), 2),
                    'exp_date_raw': expiration
                })

        lots_raw.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))

        lots = []
        remaining_pool = disponible_total

        for item in lots_raw:
            capped_qty = min(item['disponible'], max(0.0, remaining_pool))
            congelado_total = (
                float(item.get('frozen', 0.0))
                + float(item.get('transit', 0.0))
                + float(item.get('disputed', 0.0))
                + float(item.get('return_transit', 0.0))
                + float(item.get('retained', 0.0))
            )
            if capped_qty > 0.001 or congelado_total > 0.001:
                lots.append({
                    'lot_number': item['lot_number'],
                    'expiration_date': item['expiration_date'],
                    'quantity': round(float(capped_qty), 2),
                    'current_quantity': round(float(capped_qty), 2),
                    'available_quantity': round(float(capped_qty), 2),
                    'frozen_quantity': round(congelado_total, 2),
                    'frozen_merma_quantity': round(float(item.get('frozen', 0.0)), 2),
                    'frozen_transit_quantity': round(float(item.get('transit', 0.0)), 2),
                    'frozen_disputed_quantity': round(float(item.get('disputed', 0.0)), 2),
                    'return_transit_quantity': round(float(item.get('return_transit', 0.0)), 2),
                    'retained_incoming_quantity': round(float(item.get('retained', 0.0)), 2),
                    'initial_quantity': item['initial_quantity']
                })
                remaining_pool -= capped_qty

        return lots