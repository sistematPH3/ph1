from datetime import datetime  #
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
        movement = Movement(
            type='DESPACHO',
            origin_location_id=origin_id,
            destination_location_id=destination_id,
            status='EN_TRANSITO',
            user_id=created_by_id
        )
        db.session.add(movement)
        db.session.flush()

        for item in items_payload:
            product_id = int(item['product_id'])
            quantity = Decimal(str(item['quantity']))
            lot_number = str(item.get('lot_number', '')).strip()

            if not lot_number:
                raise ValueError(f"Debe especificar un lote válido para el producto ID {product_id}.")

            # Bloqueo pesimista sobre el registro específico del lote en la sede origen
            inventory = db.session.query(Inventory).filter_by(
            location_id=origin_id,
            product_id=product_id
        ).with_for_update().first()

        if not inventory or inventory.current_quantity < quantity:
            raise ValueError(f"Stock insuficiente en la sede origen. Disponible: {inventory.current_quantity if inventory else 0}")

        # Descuenta del inventario general de la sede
        inventory.current_quantity -= quantity
        inventory.transit_quantity += quantity

        exp_date_obj = datetime.strptime(item['expiration_date'], '%Y-%m-%d').date() if item.get('expiration_date') else None

        # El lote y su fecha de vencimiento se registran directamente en el detalle del movimiento
        detail = MovementDetail(
            movement_id=movement.id,
            product_id=product_id,
            quantity=quantity,
            lot_number=lot_number,
            expiration_date=exp_date_obj
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