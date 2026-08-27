from datetime import datetime
from decimal import Decimal
from sqlalchemy import or_
from app import db
from app.models import Movement, Inventory, AuditLog, Product
from app.logistics.requests.movement_dispute_validators import MovementDisputeValidator

class MovementDisputeService:

    @staticmethod
    def validate_location_can_be_deactivated(location_id):
        pending_statuses = [
            'EN_TRANSITO',
            'NOVEDAD_FALTANTE',
            'RETORNO_EMERGENCIA',
            'RECIBIDO_CON_NOVEDAD',
            'EN_DISPUTA'
        ]

        pending_count = db.session.query(Movement).filter(
            or_(
                Movement.origin_location_id == location_id,
                Movement.destination_location_id == location_id
            ),
            Movement.status.in_(pending_statuses)
        ).count()

        if pending_count > 0:
            raise ValueError(
                f"No se puede desactivar la sede ID {location_id}. Existen {pending_count} traslados pendientes de liquidación."
            )

    @staticmethod
    def resolve_dispute(movement_id, action_type, resolution_notes, admin_user_id):
        is_valid, errors = MovementDisputeValidator.validate_dispute_resolution(action_type, resolution_notes)
        if not is_valid:
            raise ValueError(errors[0])

        movement = db.session.query(Movement).filter_by(id=movement_id).with_for_update().first()
        if not movement:
            raise ValueError(f"El movimiento #{movement_id} no existe.")

        if movement.resolved_by_id is not None:
            raise ValueError(f"El movimiento #{movement_id} ya ha sido arbitrado previamente.")

        valid_dispute_statuses = [
            'NOVEDAD_FALTANTE', 'RETORNO_EMERGENCIA', 'RECIBIDO_CON_NOVEDAD',
            'EN_DISPUTA', 'FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE',
            'PRODUCTO_ERRONEO', 'SKU_CRUZADO', 'VIOLACION_CUSTODIA',
            'INCIDENCIA_TEMPERATURA', 'VENCIMIENTO_PROXIMO', 'LOTE_NO_COINCIDE',
            'RECHAZO_POR_ESPACIO', 'COMPLETADO'
        ]
        if movement.status not in valid_dispute_statuses:
            raise ValueError("El movimiento seleccionado no se encuentra en una fase que requiera arbitraje.")

        movement.resolved_by_id = admin_user_id
        movement.resolution_notes = resolution_notes.strip()

        audit_items = []
        stock_impact = {}

        if action_type == 'RESOLUCION_REINTEGRO':
            movement.status = 'CERRADO_POR_ADMIN'
            total_reintegrated = Decimal('0.00')

            for detail in movement.details:
                missing_qty = Decimal(str(detail.missing_quantity or 0))
                product = db.session.query(Product).get(detail.product_id)

                if missing_qty > Decimal('0.00'):
                    inv_origin = db.session.query(Inventory).filter_by(
                        location_id=movement.origin_location_id,
                        product_id=detail.product_id
                    ).with_for_update().first()

                    if inv_origin:
                        inv_origin.transit_quantity = max(Decimal('0.00'), inv_origin.transit_quantity - missing_qty)
                        inv_origin.current_quantity += missing_qty
                        total_reintegrated += missing_qty

                audit_items.append({
                    'product_id': detail.product_id,
                    'sku': product.sku if product else f"PROD-{detail.product_id}",
                    'lot_number': detail.lot_number,
                    'reintegrated_qty': float(missing_qty)
                })

            stock_impact = {
                'origin_transit_delta': -float(total_reintegrated),
                'origin_current_delta': float(total_reintegrated)
            }
            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_REINTEGRO'

        elif action_type == 'RESOLUCION_BAJA_EXTRAVIO':
            movement.status = 'CERRADO_CON_PERDIDA'
            total_loss = Decimal('0.00')

            for detail in movement.details:
                missing_qty = Decimal(str(detail.missing_quantity or 0))
                product = db.session.query(Product).get(detail.product_id)

                if missing_qty > Decimal('0.00'):
                    inv_origin = db.session.query(Inventory).filter_by(
                        location_id=movement.origin_location_id,
                        product_id=detail.product_id
                    ).with_for_update().first()

                    if inv_origin:
                        inv_origin.transit_quantity = max(Decimal('0.00'), inv_origin.transit_quantity - missing_qty)
                        total_loss += missing_qty

                audit_items.append({
                    'product_id': detail.product_id,
                    'sku': product.sku if product else f"PROD-{detail.product_id}",
                    'lot_number': detail.lot_number,
                    'written_off_qty': float(missing_qty)
                })

            stock_impact = {
                'origin_transit_delta': -float(total_loss),
                'financial_loss_acknowledged': True
            }
            audit_severity = 'CRITICO'
            event_name = 'RESOLUCION_BAJA_EXTRAVIO'

        elif action_type == 'RETORNO_EMERGENCIA_LIQUIDACION':
            movement.status = 'CERRADO_POR_ADMIN'
            total_recovered = Decimal('0.00')
            total_lost = Decimal('0.00')

            for detail in movement.details:
                dispatched_qty = Decimal(str(detail.quantity or 0))
                received_dest_qty = Decimal(str(detail.received_quantity or 0)) if detail.received_quantity is not None else Decimal('0.00')
                damaged_qty = Decimal(str(detail.missing_quantity or 0))

                returning_qty = max(Decimal('0.00'), dispatched_qty - received_dest_qty)
                healthy_recovered = max(Decimal('0.00'), returning_qty - damaged_qty)

                inv_origin = db.session.query(Inventory).filter_by(
                    location_id=movement.origin_location_id,
                    product_id=detail.product_id
                ).with_for_update().first()

                if inv_origin and returning_qty > Decimal('0.00'):
                    inv_origin.transit_quantity = max(Decimal('0.00'), inv_origin.transit_quantity - returning_qty)
                    inv_origin.current_quantity += healthy_recovered
                    total_recovered += healthy_recovered
                    total_lost += damaged_qty

                product = db.session.query(Product).get(detail.product_id)
                audit_items.append({
                    'product_id': detail.product_id,
                    'sku': product.sku if product else f"PROD-{detail.product_id}",
                    'lot_number': detail.lot_number,
                    'recovered_qty': float(healthy_recovered),
                    'lost_in_return_qty': float(damaged_qty)
                })

            stock_impact = {
                'origin_transit_delta': -float(total_recovered + total_lost),
                'origin_current_delta': float(total_recovered),
                'loss_written_off': float(total_lost)
            }
            audit_severity = 'CRITICO'
            event_name = 'RETORNO_EMERGENCIA_LIQUIDACION'

        elif action_type == 'RESOLUCION_LEGALIZAR_SOBRANTE':
            movement.status = 'CERRADO_POR_ADMIN'
            total_surplus = Decimal('0.00')

            for detail in movement.details:
                qty_sent = Decimal(str(detail.quantity or 0))
                qty_received = Decimal(str(detail.received_quantity or 0)) if detail.received_quantity is not None else Decimal('0.00')

                surplus_qty = max(Decimal('0.00'), qty_received - qty_sent)

                if surplus_qty > Decimal('0.00'):
                    inv_dest = db.session.query(Inventory).filter_by(
                        location_id=movement.destination_location_id,
                        product_id=detail.product_id
                    ).with_for_update().first()

                    if inv_dest:
                        inv_dest.current_quantity += surplus_qty
                        total_surplus += surplus_qty

                product = db.session.query(Product).get(detail.product_id)
                audit_items.append({
                    'product_id': detail.product_id,
                    'sku': product.sku if product else f"PROD-{detail.product_id}",
                    'lot_number': detail.lot_number,
                    'legalized_surplus_qty': float(surplus_qty)
                })

            stock_impact = {
                'destination_current_delta': float(total_surplus),
                'origin_transit_delta': 0.00
            }
            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_LEGALIZAR_SOBRANTE'

        changed_data = {
            'movement_id': movement.id,
            'event': event_name,
            'action_type': action_type,
            'origin_location_id': movement.origin_location_id,
            'destination_location_id': movement.destination_location_id,
            'items': audit_items,
            'stock_impact': stock_impact,
            'justification': movement.resolution_notes,
            'resolved_by_admin_id': admin_user_id,
            'timestamp': datetime.now().isoformat()
        }

        audit_entry = AuditLog(
            affected_table='movements',
            action=event_name,
            severity=audit_severity,
            user_id=admin_user_id,
            location_id=movement.origin_location_id,
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)
        db.session.commit()