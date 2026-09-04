import json
from decimal import Decimal
from sqlalchemy import func, or_, case
from app import db
from app.models import Inventory, Movement, MovementDetail, Purchase, PurchaseDetail, AuditLog
from app.inventory.repositories.inventory_views_repository import InventoryViewRepository

class InventoryViewService:

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
        if total_stock <= 0:
            return []

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
            # Se descuenta la cantidad física que realmente salió del origen. Con
            # sobrante (received_quantity > quantity) el excedente también salió
            # físicamente, por lo que se usa el mayor de ambos; sin sobrante
            # coincide con la guía.
            salida_fisica_central = func.greatest(
                func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity),
                MovementDetail.quantity
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
                func.sum(MovementDetail.quantity).label('total_out')
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

        audit_consumos = db.session.query(
            AuditLog.changed_data
        ).filter(
            AuditLog.location_id == loc_id,
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA', 'MERMA'])
        ).all()

        salidas_consumo = {}
        for (c_data,) in audit_consumos:
            if not c_data:
                continue
            if isinstance(c_data, str):
                try:
                    c_data = json.loads(c_data)
                except Exception:
                    continue
            if isinstance(c_data, dict):
                p_id = c_data.get('product_id')
                l_num = c_data.get('lot_number')
                qty_change = c_data.get('quantity_changed', 0.0)
                if (p_id is None or int(p_id) == prod_id) and l_num and l_num != 'N/A':
                    l_num_clean = str(l_num).strip()
                    salidas_consumo[l_num_clean] = salidas_consumo.get(l_num_clean, 0.0) + abs(float(qty_change))

        lots_raw = []
        for lot_num, data in entradas_lote.items():
            total_in = data['total_in']
            total_out_traslados = salidas_traslado.get(lot_num, 0.0)
            total_out_consumos = salidas_consumo.get(lot_num, 0.0)

            disponible = total_in - total_out_traslados - total_out_consumos

            if disponible > 0.001:
                lots_raw.append({
                    'lot_number': lot_num,
                    'expiration_date': data['expiration_date'].strftime('%Y-%m-%d') if data['expiration_date'] else '',
                    'disponible': disponible,
                    'initial_quantity': round(float(total_in), 2),
                    'exp_date_raw': data['expiration_date']
                })

        lots_raw.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))

        lots = []
        remaining_pool = total_stock

        for item in lots_raw:
            if remaining_pool <= 0.001:
                break

            capped_qty = min(item['disponible'], remaining_pool)
            if capped_qty > 0.001:
                lots.append({
                    'lot_number': item['lot_number'],
                    'expiration_date': item['expiration_date'],
                    'quantity': round(float(capped_qty), 2),
                    'current_quantity': round(float(capped_qty), 2),
                    'available_quantity': round(float(capped_qty), 2),
                    'initial_quantity': item['initial_quantity']
                })
                remaining_pool -= capped_qty

        return lots