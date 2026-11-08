# app/logistics/services/movement_audit_service.py
import datetime

from app.extensions import db
# IMPORTANTE: Asegúrate de importar User y Location desde tus modelos
from app.models import AuditLog, User, Location, Movement
from app.logistics.repositories.movement_audit_repository import MovementAuditRepository


class MovementAuditService:
    @staticmethod
    def log_movement_event(action, severity, user_id, location_id, changed_data):
        """
        Método centralizado log_movement_event para persistir los contratos JSONB inmutables generados por los submódulos 1, 2 y 3.
        """
        audit_entry = AuditLog(
            affected_table='movements',
            action=action, 
            severity=severity, 
            user_id=user_id,
            location_id=location_id,
            changed_data=changed_data 
        )
        db.session.add(audit_entry)
        db.session.commit()
        return True

    # =========================================================================
    # AYUDAS INTERNAS
    # =========================================================================
    @staticmethod
    def _hydrate_logs(logs):
        """Adjunta las instancias reales de User/Location a cada log para la vista."""
        for log in logs:
            log.user = User.query.get(log.user_id) if log.user_id else None
            log.location = Location.query.get(log.location_id) if log.location_id else None
        return logs

    @staticmethod
    def _location_name(location_id, cache):
        """Devuelve el nombre de una sede reutilizando el caché de consultas."""
        if not location_id:
            return "Sede Desconocida"
        if location_id not in cache:
            loc = Location.query.get(location_id)
            cache[location_id] = loc.name if loc else f"Sede #{location_id}"
        return cache[location_id]

    # =========================================================================
    # VISOR DE AUDITORÍA: reconstrucción cronológica por traslado
    # =========================================================================
    @staticmethod
    def get_structured_audits(filters):
        """
        Reconstruye la historia completa de CADA traslado a partir de los eventos
        JSONB inmutables de audit_logs (affected_table='movements').

        Devuelve (movements, bajas):
          - movements: lista de tarjetas, una por traslado, cada una con sus
            eventos en orden cronológico (quién, cuándo, sede, severidad, detalle).
          - bajas: resumen de mercancía dada de baja (cancelaciones) con lote,
            cantidad, quién, cuándo y a qué viaje perteneció.
        """
        logs = MovementAuditRepository.get_movement_audit_logs(filters)
        MovementAuditService._hydrate_logs(logs)

        # --- Agrupación de eventos por traslado ---
        groups = {}  # movement_id -> {'movement_id', 'origin', 'dest', 'events'}
        for log in logs:
            data = log.changed_data or {}
            movement_id = data.get('movement_id')
            if movement_id is None:
                continue

            entry = groups.setdefault(movement_id, {
                'movement_id': movement_id,
                'origin_location_id': None,
                'destination_location_id': None,
                'events': [],
            })
            entry['origin_location_id'] = entry['origin_location_id'] or data.get('origin_location_id')
            entry['destination_location_id'] = entry['destination_location_id'] or data.get('destination_location_id')
            entry['events'].append(log)

        if not groups:
            return [], []

        movement_ids = list(groups.keys())

        # --- Complementar con el estado actual del Movement (si existe) ---
        movement_map = {}
        for m in Movement.query.filter(Movement.id.in_(movement_ids)).all():
            movement_map[m.id] = m

        location_cache = {}
        movements = []

        for movement_id, entry in groups.items():
            entry['events'].sort(key=lambda e: e.timestamp or datetime.datetime.min)

            mov_obj = movement_map.get(movement_id)
            entry['origin_location_id'] = (
                entry['origin_location_id']
                or (mov_obj.origin_location_id if mov_obj else None)
                or (mov_obj.destination_location_id if mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA' else None)
            )
            entry['destination_location_id'] = (
                entry['destination_location_id']
                or (mov_obj.destination_location_id if mov_obj else None)
            )
            entry['origin_name'] = MovementAuditService._location_name(entry['origin_location_id'], location_cache)
            entry['destination_name'] = MovementAuditService._location_name(entry['destination_location_id'], location_cache)
            entry['movement'] = mov_obj
            entry['status'] = mov_obj.status if mov_obj else None
            entry['is_retorno'] = bool(mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA')
            entry['is_cancelled'] = any(
                e.action == 'CANCELACION_PRE_SALIDA' for e in entry['events']
            )
            entry['first_event'] = entry['events'][0].timestamp
            entry['last_event'] = entry['events'][-1].timestamp
            movements.append(entry)

        # Más recientes primero (según el último evento registrado)
        movements.sort(key=lambda m: m['last_event'] or datetime.datetime.min, reverse=True)

        # --- Construcción del resumen de BAJAS (cancelaciones) ---
        bajas = []
        for movement_id, entry in groups.items():
            # Lotes y cantidades originales del despacho de ese viaje
            dispatch_items = None
            dispatch_user = None
            for e in entry['events']:
                data = e.changed_data or {}
                if e.action == 'DESPACHO_EMISION':
                    dispatch_items = data.get('items', [])
                    dispatch_user = e.user
                    break

            for e in entry['events']:
                if e.action != 'CANCELACION_PRE_SALIDA':
                    continue
                data = e.changed_data or {}
                bajas.append({
                    'movement_id': movement_id,
                    'timestamp': e.timestamp,
                    'location_id': e.location_id,
                    'location_name': e.location.name if e.location else '—',
                    'user_name': e.user.name if e.user else f"Usuario ID: {e.user_id}",
                    'dispatcher_name': dispatch_user.name if dispatch_user else '—',
                    'reason': data.get('reason', ''),
                    'origin_name': entry['origin_name'],
                    'destination_name': entry['destination_name'],
                    'items': dispatch_items or [],
                    'total_reverted': sum(
                        float(i.get('dispatched_qty', 0)) for i in (dispatch_items or [])
                    ),
                })

        bajas.sort(key=lambda b: b['timestamp'] or datetime.datetime.min, reverse=True)

        return movements, bajas

    # =========================================================================
    # RANGO DE FECHAS DISPONIBLE (para limitar el calendario del visor)
    # =========================================================================
    @staticmethod
    def get_movement_audit_date_range(filters):
        """Devuelve (min, max) como objetos datetime con los registros existentes."""
        return MovementAuditRepository.get_movement_audit_date_range(filters)