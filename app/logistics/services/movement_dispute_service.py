from app.extensions import db
from app.models import Movement, Inventory, AuditLog
from datetime import datetime
from sqlalchemy import or_

class MovementDisputeService:

    @staticmethod
    def validate_location_can_be_deactivated(location_id):
        """
        Valida que la sede no tenga traslados en tránsito ni disputas pendientes.
        Lanza ValueError si tiene pendientes para bloquear la desactivación.
        """
        pending_statuses = [
            'EN_TRANSITO', 
            'NOVEDAD_FALTANTE', 
            'RETORNO_EMERGENCIA', 
            'RECIBIDO_CON_NOVEDAD', 
            'EN_DISPUTA'
        ]

        pending_count = Movement.query.filter(
            or_(
                Movement.origin_location_id == location_id,
                Movement.destination_location_id == location_id
            ),
            Movement.status.in_(pending_statuses)
        ).count()

        if pending_count > 0:
            raise ValueError(
                f"No se puede desactivar la sede ID {location_id}. "
                f"Existen {pending_count} traslados pendientes de liquidación "
                f"(en tránsito, retorno o con faltantes en disputa)."
            )

    @staticmethod
    def resolve_dispute(movement_id, action_type, resolution_notes, admin_user_id):
        """
        Ejecuta la lógica transaccional de arbitraje dictaminada por el Administrador.
        """
        movement = Movement.query.get_or_404(movement_id)
        
        # Validación de seguridad: evitar resolver movimientos ya arbitrados
        if movement.resolved_by_id is not None:
            raise ValueError(f"El movimiento #{movement_id} ya ha sido arbitrado previamente.")

        valid_dispute_statuses = [
            'NOVEDAD_FALTANTE', 'RETORNO_EMERGENCIA', 'RECIBIDO_CON_NOVEDAD', 
            'EN_DISPUTA', 'FALTANTE_CONTEO', 'COMPLETADO'
        ]
        if movement.status not in valid_dispute_statuses:
            raise ValueError("El movimiento seleccionado no se encuentra en una fase que requiera arbitraje.")

        if not resolution_notes or len(resolution_notes.strip()) < 15:
            raise ValueError("La justificación legal o acta es obligatoria y debe tener al menos 15 caracteres.")

        # Asignamos los datos del veredicto a la cabecera del movimiento
        movement.resolved_by_id = admin_user_id
        movement.resolution_notes = resolution_notes.strip()

        # =========================================================================
        # OPCIÓN 1: REINTEGRO AL ORIGEN
        # =========================================================================
        if action_type == 'RESOLUCION_REINTEGRO':
            movement.status = 'CERRADO_POR_ADMIN'
            
            for detail in movement.details:
                qty_sent = detail.quantity or 0
                qty_received = detail.received_quantity or 0

                inventory_origin = Inventory.query.with_for_update().filter_by(
                    location_id=movement.origin_location_id,
                    product_id=detail.product_id
                ).first()

                # CASO A: FALTANTE (Se enviaron 5 kg y llegaron 2 kg -> faltan 3 kg)
                # Los 3 kg sí fueron restados de Central y están congelados en 'transit_quantity'.
                # Al reintegar, se liberan del tránsito y regresan al disponible de Central.
                if getattr(detail, 'missing_quantity', 0) > 0:
                    missing = detail.missing_quantity
                    if inventory_origin:
                        inventory_origin.transit_quantity = max(0, inventory_origin.transit_quantity - missing)
                        inventory_origin.current_quantity += missing

                # CASO B: SOBRANTE (Se enviaron 5 kg y llegaron 20 kg -> sobran 15 kg)
                # El camión devuelve los 15 kg físicos a Central.
                # Digitalmente NO se hace ningún cálculo porque Central NUNCA descontó esos 15 kg.
                # Su base de datos ya marcaba 45 kg disponibles.
                elif qty_received > qty_sent:
                    pass  # El stock en BD de Central ya es el correcto (45 kg).

            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_REINTEGRO'

        # =========================================================================
        # OPCIÓN 2: LEGALIZAR SOBRANTE EN DESTINO
        # (Si el administrador autoriza que la sucursal receptora se quede el excedente)
        # =========================================================================
        elif action_type in ['RESOLUCION_LEGALIZAR_SOBRANTE', 'RESOLUCION_INGRESO_DESTINO']:
            movement.status = 'CERRADO_POR_ADMIN'
            
            for detail in movement.details:
                qty_sent = detail.quantity or 0
                qty_received = detail.received_quantity or 0

                if qty_received > qty_sent:
                    sobrante = qty_received - qty_sent

                    inventory_dest = Inventory.query.filter_by(
                        location_id=movement.destination_location_id,
                        product_id=detail.product_id
                    ).first()

                    # Se le suma el excedente únicamente a la sucursal que se lo quedó
                    if inventory_dest:
                        inventory_dest.current_quantity += sobrante

            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_LEGALIZAR_SOBRANTE'

        # =========================================================================
        # OPCIÓN 3: BAJA POR EXTRAVÍO / ROBO
        # =========================================================================
        elif action_type == 'RESOLUCION_BAJA_EXTRAVIO':
            movement.status = 'CERRADO_CON_PERDIDA'
            
            for detail in movement.details:
                if getattr(detail, 'missing_quantity', 0) > 0:
                    missing = detail.missing_quantity
                    inventory_origin = Inventory.query.filter_by(
                        location_id=movement.origin_location_id,
                        product_id=detail.product_id
                    ).first()
                    
                    if inventory_origin:
                        inventory_origin.transit_quantity = max(0, inventory_origin.transit_quantity - missing)

            audit_severity = 'CRITICO'
            event_name = 'RESOLUCION_BAJA_EXTRAVIO'

        # =========================================================================
        # OPCIÓN 4: RETORNO DE EMERGENCIA / LIQUIDACIÓN
        # =========================================================================
        elif action_type == 'RETORNO_EMERGENCIA_LIQUIDACION':
            movement.status = 'CERRADO_POR_ADMIN'
            CENTRAL_LOCATION_ID = 1  # ID del Almacén Central

            for detail in movement.details:
                inventory_origin = Inventory.query.with_for_update().filter_by(
                    location_id=movement.origin_location_id,
                    product_id=detail.product_id
                ).first()

                transit_to_clear = (detail.quantity or 0) - (detail.received_quantity or 0)

                if inventory_origin and transit_to_clear > 0:
                    inventory_origin.transit_quantity = max(0, inventory_origin.transit_quantity - transit_to_clear)

                inventory_dest = Inventory.query.with_for_update().filter_by(
                    location_id=movement.destination_location_id,
                    product_id=detail.product_id
                ).first()

                qty_received = detail.received_quantity or 0
                if inventory_dest and qty_received > 0:
                    inventory_dest.current_quantity = max(0, inventory_dest.current_quantity - qty_received)

                inventory_central = Inventory.query.with_for_update().filter_by(
                    location_id=CENTRAL_LOCATION_ID,
                    product_id=detail.product_id
                ).first()

                if not inventory_central:
                    inventory_central = Inventory(
                        location_id=CENTRAL_LOCATION_ID,
                        product_id=detail.product_id,
                        current_quantity=0,
                        transit_quantity=0,
                        min_stock=0
                    )
                    db.session.add(inventory_central)

                damaged_qty = getattr(detail, 'missing_quantity', 0) or 0
                total_returning = transit_to_clear + qty_received
                recovered_qty = max(0, total_returning - damaged_qty)

                inventory_central.current_quantity += recovered_qty

            audit_severity = 'CRITICO'
            event_name = 'RETORNO_EMERGENCIA_LIQUIDACION'
        else:
            raise ValueError("Tipo de resolución no reconocido por el sistema.")

        # Registro inmutable en la bitácora de auditoría
        audit_log = AuditLog(
            affected_table='movements',
            action=event_name,
            severity=audit_severity,
            user_id=admin_user_id,
            location_id=movement.origin_location_id,
            timestamp=datetime.utcnow(),
            changed_data={
                "movement_id": movement.id,
                "event": event_name,
                "status_result": movement.status,
                "resolution_notes": movement.resolution_notes,
                "resolved_by_admin_id": admin_user_id
            }
        )
        db.session.add(audit_log)
        db.session.commit()