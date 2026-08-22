from app.extensions import db
from app.models import Movement, Inventory, AuditLog
from datetime import datetime

class MovementDisputeService:

    @staticmethod
    def resolve_dispute(movement_id, action_type, resolution_notes, admin_user_id):
        """
        Ejecuta la lógica transaccional de arbitraje dictaminada por el Administrador.
        """
        movement = Movement.query.get_or_404(movement_id)
        
        if movement.status not in ['NOVEDAD_FALTANTE', 'RETORNO_EMERGENCIA']:
            raise ValueError("El movimiento seleccionado no se encuentra en una fase que requiera arbitraje.")

        if not resolution_notes or len(resolution_notes.strip()) < 15:
            raise ValueError("La justificación legal o acta es obligatoria y debe tener al menos 15 caracteres.")

        # Asignamos los datos del veredicto a la cabecera del movimiento
        movement.resolved_by_id = admin_user_id
        movement.resolution_notes = resolution_notes.strip()

        # Procesamos según el tipo de resolución seleccionada
        if action_type == 'RESOLUCION_REINTEGRO':
            movement.status = 'CERRADO_POR_ADMIN'
            
            # Devolvemos el faltante retenido en tránsito de vuelta al disponible del origen
            for detail in movement.details:
                if detail.missing_quantity > 0:
                    inventory = Inventory.query.filter_by(
                        location_id=movement.origin_location_id,
                        product_id=detail.product_id
                    ).first()
                    
                    if inventory:
                        inventory.transit_quantity -= detail.missing_quantity
                        inventory.current_quantity += detail.missing_quantity

            audit_severity = 'NORMAL'
            event_name = 'RESOLUCION_REINTEGRO'

        elif action_type == 'RESOLUCION_BAJA_EXTRAVIO':
            movement.status = 'CERRADO_CON_PERDIDA'
            
            # Se descuenta definitivamente del tránsito del origen sin sumarse a ningún disponible (Pérdida patrimonial)
            for detail in movement.details:
                if detail.missing_quantity > 0:
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
