import json
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, case
from app import db
from app.models import Inventory, Movement, MovementDetail, Product, Purchase, PurchaseDetail, AuditLog

class MovementDispatchRepository:

    @staticmethod
    def get_inventory_for_update(location_id, product_id):
        return db.session.query(Inventory).filter_by(
            location_id=location_id,
            product_id=product_id
        ).with_for_update().first()

    @staticmethod
    def get_product_lots_available(location_id, product_id):
        loc_id = int(location_id)
        prod_id = int(product_id)

        inventory = db.session.query(Inventory).filter_by(
            location_id=loc_id,
            product_id=prod_id
        ).first()

        total_stock = float(inventory.current_quantity) if inventory else 0.0
        if total_stock <= 0:
            return total_stock, []

        entradas_lote = {}
        salidas_traslado = {}

        if loc_id == 1:
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

            despachos = db.session.query(
                MovementDetail.lot_number,
                func.sum(MovementDetail.quantity).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == 1,
                Movement.status.notin_(['CANCELADO', 'CANCELADO_EMISOR', 'ANULADO', 'RECHAZADO']),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None)
            ).group_by(MovementDetail.lot_number).all()

            salidas_traslado = {d.lot_number.strip(): float(d.total_out or 0.0) for d in despachos if d.lot_number}

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

            despachos_sucursal = db.session.query(
                MovementDetail.lot_number,
                func.sum(MovementDetail.quantity).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == loc_id,
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
                    'available_quantity': disponible,
                    'expiration_date': data['expiration_date'].strftime('%Y-%m-%d') if data['expiration_date'] else '',
                    'exp_date_raw': data['expiration_date']
                })

        lots_raw.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))

        lots = []
        remaining_pool = total_stock

        for item in lots_raw:
            if remaining_pool <= 0.001:
                break

            capped_qty = min(item['available_quantity'], remaining_pool)
            if capped_qty > 0.001:
                lots.append({
                    'lot_number': item['lot_number'],
                    'available_quantity': round(float(capped_qty), 2),
                    'expiration_date': item['expiration_date']
                })
                remaining_pool -= capped_qty

        return total_stock, lots

    @staticmethod
    def create_dispatch_transaction(origin_id, destination_id, created_by_id, items_payload):
        movement = Movement(
            type='DESPACHO',
            origin_location_id=origin_id,
            destination_location_id=destination_id,
            status='EN_TRANSITO',
            user_id=created_by_id,
            date=datetime.now()
        )
        db.session.add(movement)
        db.session.flush()

        audit_items = []
        total_dispatched = Decimal('0.00')

        for item in items_payload:
            product_id = int(item['product_id'])
            quantity = Decimal(str(item['quantity']))
            lot_number = str(item.get('lot_number', '')).strip()

            if not lot_number:
                raise ValueError(f"Debe especificar un lote válido para el insumo ID {product_id}.")

            inventory = MovementDispatchRepository.get_inventory_for_update(origin_id, product_id)

            if not inventory:
                raise ValueError(f"El insumo ID {product_id} no está registrado en la sede origen.")

            if inventory.current_quantity < quantity:
                raise ValueError(f"Stock insuficiente para el insumo ID {product_id}. Disponible: {inventory.current_quantity}, Solicitado: {quantity}")

            inventory.current_quantity -= quantity
            inventory.transit_quantity += quantity
            total_dispatched += quantity

            exp_date_obj = None
            if item.get('expiration_date'):
                try:
                    exp_date_obj = datetime.strptime(item['expiration_date'], '%Y-%m-%d').date()
                except ValueError:
                    exp_date_obj = None

            detail = MovementDetail(
                movement_id=movement.id,
                product_id=product_id,
                quantity=quantity,
                missing_quantity=Decimal('0.00'),
                lot_number=lot_number,
                expiration_date=exp_date_obj
            )
            db.session.add(detail)

            product = db.session.query(Product).get(product_id)
            audit_items.append({
                'product_id': product_id,
                'sku': product.sku if product else f"PROD-{product_id}",
                'product_name': product.name if product else f"Insumo #{product_id}",
                'lot_number': lot_number,
                'expiration_date': str(exp_date_obj) if exp_date_obj else None,
                'dispatched_qty': float(quantity)
            })

        changed_data = {
            'movement_id': movement.id,
            'event': 'DESPACHO_EMISION',
            'origin_location_id': origin_id,
            'destination_location_id': destination_id,
            'items': audit_items,
            'stock_impact': {
                'origin_current_delta': -float(total_dispatched),
                'origin_transit_delta': float(total_dispatched)
            },
            'user_id': created_by_id,
            'timestamp': datetime.now().isoformat()
        }

        audit_entry = AuditLog(
            affected_table='movements',
            action='DESPACHO_EMISION',
            severity='NORMAL',
            user_id=created_by_id,
            location_id=origin_id,
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

        return movement

    @staticmethod
    def cancel_dispatch_transaction(movement_id, user_id, reason):
        movement = db.session.query(Movement).filter_by(id=movement_id).with_for_update().first()

        if not movement:
            raise ValueError("El movimiento especificado no existe.")

        if movement.status != 'EN_TRANSITO':
            raise ValueError(f"No se puede cancelar un movimiento en estado '{movement.status}'.")

        details = db.session.query(MovementDetail).filter_by(movement_id=movement.id).all()
        total_reverted = Decimal('0.00')

        for detail in details:
            inventory = MovementDispatchRepository.get_inventory_for_update(
                movement.origin_location_id, detail.product_id
            )

            if inventory:
                inventory.current_quantity += detail.quantity
                inventory.transit_quantity -= detail.quantity
                total_reverted += detail.quantity

        movement.status = 'CANCELADO_EMISOR'
        movement.resolution_notes = reason.strip()
        movement.resolved_by_id = user_id

        changed_data = {
            'movement_id': movement.id,
            'event': 'CANCELACION_PRE_SALIDA',
            'origin_location_id': movement.origin_location_id,
            'destination_location_id': movement.destination_location_id,
            'reason': reason.strip(),
            'stock_impact': {
                'origin_current_delta': float(total_reverted),
                'origin_transit_delta': -float(total_reverted)
            },
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }

        audit_entry = AuditLog(
            affected_table='movements',
            action='CANCELACION_PRE_SALIDA',
            severity='ALERTA',
            user_id=user_id,
            location_id=movement.origin_location_id,
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

        return movement