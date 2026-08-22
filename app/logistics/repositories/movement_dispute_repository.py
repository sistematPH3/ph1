from app.extensions import db
from app.models import Movement

class MovementDisputeRepository:
    
    @staticmethod
    def get_pending_disputes():
        """
        Retorna todos los movimientos que se encuentran en estatus de novedad
        o incidencias, listos para ser arbitrados por el Administrador.
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
        ).order_by(Movement.date.desc()).all()

    @staticmethod
    def get_movement_by_id(movement_id):
        """Busca un movimiento específico por su ID."""
        return Movement.query.get(movement_id)