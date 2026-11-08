# app/logistics/repositories/movement_dispute_repository.py

from app.extensions import db
from app.models import Movement, MovementDetail
from sqlalchemy.orm import joinedload

class MovementDisputeRepository:
    
    @staticmethod
    def get_pending_disputes():
        """
        Retorna todos los movimientos que se encuentran en estatus de novedad
        o incidencias, listos para ser arbitrados por el Administrador.
        
        MEJORADO: Ahora carga las relaciones (locations, products) para evitar
        queries N+1 y mostrar nombres en lugar de IDs.
        """
        return Movement.query.filter(
            Movement.status.in_([
                'FALTANTE_CONTEO',
                'SOBRANTE_EXCEDENTE',
                'PRODUCTO_ERRONEO',
                'VIOLACION_CUSTODIA',
                'INCIDENCIA_TEMPERATURA',
                'VENCIMIENTO_PROXIMO',
                'LOTE_NO_COINCIDE',
                'RECHAZO_POR_ESPACIO',
                'RETORNO_EMERGENCIA',
                'NOVEDAD_FALTANTE'
            ])
        ).options(
            joinedload(Movement.origin_location),
            joinedload(Movement.destination_location),
            joinedload(Movement.details).joinedload(MovementDetail.product)
        ).order_by(Movement.date.desc()).all()

    @staticmethod
    def get_movement_by_id(movement_id):
        """Busca un movimiento específico por su ID con relaciones cargadas."""
        return Movement.query.options(
            joinedload(Movement.origin_location),
            joinedload(Movement.destination_location),
            joinedload(Movement.details).joinedload(MovementDetail.product)
        ).get(movement_id)