from decimal import Decimal
from app import db
from app.models import Inventory, Movement, MovementDetail

class MovementDispatchRepository:

    @staticmethod
    def get_inventory_for_update(location_id, product_id):
        """
        Obtiene la fila de inventario aplicando un bloqueo pesimista (SELECT ... FOR UPDATE).
        """
        return db.session.query(Inventory).filter_by(
            location_id=location_id,
            product_id=product_id
        ).with_for_update().first()

    @staticmethod
    def create_dispatch_transaction(origin_id, destination_id, created_by_id, items_payload):
        """
        Ejecuta la reserva matemática bajo bloqueo pesimista:
        Resta de current_quantity y suma a transit_quantity en la sede origen.
        """
        # 1. Crear el registro cabecera en la tabla movements
        movement = Movement(
            type='DESPACHO',
            origin_location_id=origin_id,
            destination_location_id=destination_id,
            status='EN_TRANSITO',  # Estado inicial inmutable
            user_id=created_by_id
        )
        db.session.add(movement)
        db.session.flush()  # Genera el ID del movimiento sin cerrar la transacción

        # 2. Procesar cada renglón del detalle
        for item in items_payload:
            product_id = int(item['product_id'])
            quantity = Decimal(str(item['quantity']))
            lot_number = item.get('lot_number', '').strip()
            exp_date_str = item.get('expiration_date')

            # Bloqueo Pesimista
            inventory = MovementDispatchRepository.get_inventory_for_update(origin_id, product_id)

            if not inventory:
                raise ValueError(f"El producto ID {product_id} no está registrado en el inventario de la sede origen.")

            if inventory.current_quantity < quantity:
                raise ValueError(
                    f"Stock insuficiente para el producto ID {product_id}. "
                    f"Disponible: {inventory.current_quantity}, Solicitado: {quantity}"
                )

            # Transferencia de saldos de custodia
            inventory.current_quantity -= quantity
            inventory.transit_quantity += quantity

            # Crear renglón en movement_details
            detail = MovementDetail(
                movement_id=movement.id,
                product_id=product_id,
                quantity=quantity,
                lot_number=lot_number if lot_number else None,
                expiration_date=exp_date_str if exp_date_str else None
            )
            db.session.add(detail)

        return movement

    @staticmethod
    def cancel_dispatch_transaction(movement_id):
        """
        Revierte la reserva matemática en origen si el traslado está en estado EN_TRANSITO.
        """
        movement = db.session.query(Movement).filter_by(id=movement_id).with_for_update().first()

        if not movement:
            raise ValueError("El movimiento especificado no existe.")

        if movement.status != 'EN_TRANSITO':
            raise ValueError(f"No se puede cancelar un movimiento en estado '{movement.status}'.")

        # Obtener los detalles asociados
        details = db.session.query(MovementDetail).filter_by(movement_id=movement.id).all()

        for detail in details:
            inventory = MovementDispatchRepository.get_inventory_for_update(
                movement.origin_location_id, detail.product_id
            )

            if inventory:
                # Revertir la reserva matemática
                inventory.current_quantity += detail.quantity
                inventory.transit_quantity -= detail.quantity

        movement.status = 'CANCELADO_EMISOR'
        return movement