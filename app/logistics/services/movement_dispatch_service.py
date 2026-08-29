from app import db
from app.logistics.requests.movement_dispatch_validators import MovementDispatchValidator
from app.logistics.repositories.movement_dispatch_repository import MovementDispatchRepository

class MovementDispatchService:

    @staticmethod
    def get_lots_for_dispatch(location_id, product_id):
        if not location_id or not product_id:
            return {"success": False, "total_stock": 0, "lots": []}, 400

        total_stock, lots = MovementDispatchRepository.get_product_lots_available(location_id, product_id)
        return {
            "success": True,
            "total_stock": total_stock,
            "lots": lots
        }, 200

    @staticmethod
    def execute_dispatch(user, payload):
        is_valid, errors = MovementDispatchValidator.validate_dispatch_payload(payload)
        if not is_valid:
            return {"success": False, "errors": errors}, 400

        origin_id = int(payload['origin_location_id'])
        destination_id = int(payload['destination_location_id'])

        user_locations = getattr(user, 'locations', None)
        user_loc_id = user_locations[0].id if user_locations else getattr(user, 'location_id', None)

        if getattr(user, 'role_id', None) not in [1] and user_loc_id != origin_id:
            return {
                "success": False,
                "errors": ["No tiene permisos para emitir despachos desde una sede distinta a la asignada."]
            }, 403

        # Si el despacho se originó como reposición complementaria desde una
        # disputa, se conserva el vínculo para poder auto-cancelarlo si esa
        # disputa se abandona sin resolución.
        source_dispute_id = payload.get('source_dispute_id')
        if source_dispute_id is not None:
            try:
                source_dispute_id = int(source_dispute_id)
            except (TypeError, ValueError):
                source_dispute_id = None

        try:
            movement = MovementDispatchRepository.create_dispatch_transaction(
                origin_id=origin_id,
                destination_id=destination_id,
                created_by_id=user.id,
                items_payload=payload['items'],
                source_dispute_id=source_dispute_id
            )
            db.session.commit()
            return {
                "success": True,
                "message": f"Despacho #{movement.id} emitido exitosamente.",
                "movement_id": movement.id
            }, 201

        except ValueError as ve:
            db.session.rollback()
            return {"success": False, "errors": [str(ve)]}, 422
        except Exception as e:
            db.session.rollback()
            return {"success": False, "errors": [f"Error interno en la transacción: {str(e)}"]}, 500

    @staticmethod
    def execute_precancellation(user, movement_id: int, reason: str):
        if not reason or not reason.strip():
            return {"success": False, "errors": ["El motivo de cancelación es obligatorio."]}, 400

        try:
            movement_check = db.session.query(db.models.Movement if hasattr(db, 'models') else MovementDispatchRepository).get(movement_id)
        except Exception:
            movement_check = None

        try:
            movement = MovementDispatchRepository.cancel_dispatch_transaction(movement_id, user.id, reason)
            
            user_locations = getattr(user, 'locations', None)
            user_loc_id = user_locations[0].id if user_locations else getattr(user, 'location_id', None)

            if getattr(user, 'role_id', None) not in [1] and user_loc_id != movement.origin_location_id:
                db.session.rollback()
                return {
                    "success": False,
                    "errors": ["Solo el Administrador o el personal de la sede de origen pueden cancelar esta pre-salida."]
                }, 403

            db.session.commit()
            return {
                "success": True,
                "message": f"Traslado #{movement_id} cancelado correctamente. El stock ha sido revertido."
            }, 200

        except ValueError as ve:
            db.session.rollback()
            return {"success": False, "errors": [str(ve)]}, 422
        except Exception as e:
            db.session.rollback()
            return {"success": False, "errors": [f"Error al cancelar la salida: {str(e)}"]}, 500