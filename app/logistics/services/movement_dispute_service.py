from app.extensions import db
from app.models import Movement, Inventory, AuditLog
from datetime import datetime
from sqlalchemy import or_  # <-- Asegúrate de importar or_

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

        # Contar traslados donde la sede sea origen o destino y sigan pendientes
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
        
        # Validación de seguridad: evitar resolver movimientos ya arbitrados o no válidos
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

        # Procesamos según el tipo de resolución seleccionada
        if action_type == 'RESOLUCION_REINTEGRO':
            movement.status = 'CERRADO_POR_ADMIN'
            
            for detail in movement.details:
                qty_sent = detail.quantity or 0
                qty_received = detail.received_quantity or 0

                # Inventario de la sede origen (Almacén Central)
                inventory_origin = Inventory.query.filter_by(
                    location_id=movement.origin_location_id,
                    product_id=detail.product_id
                ).first()

                # Inventario de la sede destino (Receptora)
                inventory_dest = Inventory.query.filter_by(
                    location_id=movement.destination_location_id,
                    product_id=detail.product_id
                ).first()

                # CASO 1: FALTANTE (Se envió más de lo que llegó)
                if getattr(detail, 'missing_quantity', 0) > 0:
                    if inventory_origin:
                        inventory_origin.transit_quantity -= detail.missing_quantity
                        inventory_origin.current_quantity += detail.missing_quantity

                # CASO 2: SOBRANTE (Se recibió más de lo que se envió, ej: 90 recibidos vs 50 enviados)
                elif qty_received > qty_sent:
                    sobrante = qty_received - qty_sent

                    # 1. Reintegrar el sobrante al disponible del Almacén Central (Origen)
                    if inventory_origin:
                        inventory_origin.current_quantity += sobrante

                    # 2. Descontar el sobrante de la sede receptora si esta se lo había sumado indebidamente
                    if inventory_dest:
                        inventory_dest.current_quantity -= sobrante

            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_REINTEGRO'

        elif action_type == 'RESOLUCION_BAJA_EXTRAVIO':
            movement.status = 'CERRADO_CON_PERDIDA'
            
            # Se descuenta definitivamente del tránsito del origen sin sumarse a ningún disponible (Pérdida patrimonial)
            for detail in movement.details:
                if getattr(detail, 'missing_quantity', 0) > 0:
                    inventory = Inventory.query.filter_by(
                        location_id=movement.origin_location_id,
                        product_id=detail.product_id
                    ).first()
                    
                    if inventory:
                        inventory.transit_quantity -= detail.missing_quantity

            audit_severity = 'CRITICO'
            event_name = 'RESOLUCION_BAJA_EXTRAVIO'

        elif action_type == 'RETORNO_EMERGENCIA_LIQUIDACION':
            movement.status = 'CERRADO_POR_ADMIN'
            
            # Liquidación del retorno físico a central
            for detail in movement.details:
                inventory = Inventory.query.filter_by(
                    location_id=movement.origin_location_id,
                    product_id=detail.product_id
                ).first()
                
                if inventory:
                    # Liberamos el tránsito total que venía de regreso
                    transit_to_clear = detail.quantity - (detail.received_quantity or 0)
                    inventory.transit_quantity -= transit_to_clear

            audit_severity = 'CRITICO'
            event_name = 'RETORNO_EMERGENCIA_LIQUIDACION'
        else:
            raise ValueError("Tipo de resolución no reconocido por el sistema.")

        # Registro inmutable en la bitácora de auditoría (AuditLog)
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