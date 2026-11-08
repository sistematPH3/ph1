import json
from datetime import datetime

from app.extensions import db
from app.models import AuditLog, Location, Movement, Notification, Product, User
from sqlalchemy import or_


# Acciones de auditoría que registran la recepción (y su clasificación).
RECEPTION_AUDIT_ACTIONS = (
    'RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD', 'RECEPCION_CONFORME'
)

# Tipo de notificación que representa una respuesta del Administrador.
RESPONSE_NOTIFICATION_TYPE = 'RESPUESTA_TRASLADO'

# Etiquetas legibles de cada clasificación de novedad reportada en recepción.
NOVEDAD_LABELS = {
    'FALTANTE_CONTEO': 'Faltante de Conteo',
    'SOBRANTE_EXCEDENTE': 'Sobrante / Excedente',
    'PRODUCTO_ERRONEO': 'Producto Erróneo',
    'VIOLACION_CUSTODIA': 'Violación de Custodia',
    'INCIDENCIA_TEMPERATURA': 'Incidencia Temperatura',
    'VENCIMIENTO_PROXIMO': 'Vencimiento Próximo',
    'LOTE_NO_COINCIDE': 'Lote no Coincide',
    'RECHAZO_POR_ESPACIO': 'Rechazo por Espacio',
    'RETORNO_EMERGENCIA': 'Retorno de Emergencia',
    'NOVEDAD_FALTANTE': 'Novedad Faltante',
    'INCIDENCIA_MIXTA': 'Incidencia Mixta',
}

# Etiquetas de la novedad específica que tuvo cada producto dentro del traslado.
SPECIFIC_NOVELTY_LABELS = {
    'FALTANTE': 'Faltante',
    'SOBRANTE': 'Sobrante',
    'CONFORME': 'Conforme',
    'INCIDENCIA_TEMPERATURA': 'Incidencia Temperatura',
    'VIOLACION_CUSTODIA': 'Violación de Custodia',
    'VENCIMIENTO_PROXIMO': 'Vencimiento Próximo',
    'LOTE_NO_COINCIDE': 'Lote no Coincide',
    'PRODUCTO_ERRONEO': 'Producto Erróneo',
    'RECHAZO_POR_ESPACIO': 'Rechazo por Espacio',
}

# Etiquetas de las decisiones administrativas tomadas en el arbitraje.
RESOLUTION_ACTION_LABELS = {
    'ACEPTAR_RECEPCION': 'Aceptar recepción',
    'RECEPCION_CONFORME_FEFO': 'Recepcion conforme FEFO',
    'INCIDENCIA_INTERNA': 'Incidencia interna',
    'CORREGIR_LOTE': 'Corregir lote',
    'RESOLUCION_REINTEGRO': 'Reintegrar al origen',
    'RETORNO_EMERGENCIA': 'Retorno de emergencia',
    'RESOLUCION_BAJA_EXTRAVIO': 'Baja / extravío',
    'RESOLUCION_ACREDITAR_DESTINO': 'Acreditar destino',
    'SIN_ACCION': 'Sin acción',
}


class ResponseInboxRepository:
    """
    Bandeja de respuestas: los movimientos que ya recibieron un dictamen del
    Administrador. Una "respuesta" existe cuando se registró una auditoría
    RESOLUCION_DISPUTA sobre el traslado (el estado del movimiento queda en
    COMPLETADO y el acta administrativa queda en resolution_notes / el JSON de
    la auditoría).

    Desde la mejora del modelo, el estado "leído/no leído" vive en el servidor
    (tabla notifications, type RESPUESTA_TRASLADO), no en el navegador. Al
    resolver una disputa se crea una Notification por cada receptor.

    Además, se adjunta la clasificación original de la novedad y el detalle de
    productos de la recepción (obtenidos de la auditoría RECEPCION_NOVEDAD),
    para identificar de un vistazo a qué traslado corresponde la respuesta.
    """

    @staticmethod
    def _read_data(log):
        """Devuelve changed_data como dict, soportando JSONB o string JSON."""
        data = getattr(log, 'changed_data', None)
        if data is None:
            return {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _movement_id(data):
        return data.get("movement_id")

    @staticmethod
    def get_unread_count(user):
        """Cuenta las respuestas pendientes de leer por el usuario en el servidor."""
        return Notification.query.filter_by(
            user_id=user.id,
            type=RESPONSE_NOTIFICATION_TYPE,
            is_read=False,
        ).count()

    @staticmethod
    def get_admin_responses(user, limit=None):
        """Devuelve los traslados resueltos por el administrador, más reciente primero.

        - El usuario normal solo ve las respuestas de los traslados que pasan
          por sus sedes asignadas (origen o destino): son exactamente las que
          tienen una Notification RESPUESTA_TRASLADO a su nombre.
        - Admin y Finanzas lo ven todo (bandeja global).
        """
        # 0) Estado "leído" del usuario (servidor).
        notifications = Notification.query.filter_by(
            user_id=user.id, type=RESPONSE_NOTIFICATION_TYPE
        ).all()
        notif_map = {
            n.movement_id: n for n in notifications if n.movement_id is not None
        }

        # 1) Auditorías que representan un dictamen emitido por el admin.
        resolution_logs = (
            AuditLog.query
            .filter(AuditLog.action == 'RESOLUCION_DISPUTA')
            .order_by(AuditLog.timestamp.desc())
            .all()
        )

        is_global = user.is_admin or user.is_finance
        resolution_map = {}
        for log in resolution_logs:
            data = ResponseInboxRepository._read_data(log)
            mov_id = ResponseInboxRepository._movement_id(data)
            if mov_id is None or mov_id in resolution_map:
                continue
            if not is_global and mov_id not in notif_map:
                continue  # este usuario no fue notificado de esa respuesta.
            resolution_map[mov_id] = {
                "resolved_at": log.timestamp,
                "resolved_by_id": log.user_id,
                "notes": data.get("general_notes") or "",
                "summary": data.get("resolution_summary") or {},
                "items": data.get("items") or [],
            }

        if not resolution_map:
            return []

        # 2) Cargar los movimientos con respuesta.
        movements = Movement.query.filter(Movement.id.in_(list(resolution_map.keys()))).all()

        # 3) Auditorías de recepción de estos mismos movimientos: recuperan la
        #    clasificación original de la novedad y el detalle de lo recibido.
        reception_map = {}
        reception_logs = (
            AuditLog.query
            .filter(AuditLog.action.in_(RECEPTION_AUDIT_ACTIONS))
            .filter(AuditLog.changed_data.op('->>')('movement_id').in_(
                [str(m.id) for m in movements]
            ))
            .order_by(AuditLog.timestamp.asc())
            .all()
        )
        for log in reception_logs:
            data = ResponseInboxRepository._read_data(log)
            mov_id = ResponseInboxRepository._movement_id(data)
            if mov_id is None:
                continue
            reception_map[int(mov_id)] = data  # última recepción por movimiento

        # 4) Mapas auxiliares de autores, sedes y productos.
        resolved_ids = [r["resolved_by_id"] for r in resolution_map.values() if r["resolved_by_id"]]
        reported_ids = [
            r.get("received_by_user_id") for r in reception_map.values()
            if r.get("received_by_user_id")
        ]
        users = {u.id: u for u in User.query.filter(
            User.id.in_(list(set(resolved_ids + reported_ids)) or [0])
        ).all()}
        locations = {loc.id: loc for loc in Location.query.all()}

        product_ids = set()
        for data in reception_map.values():
            for it in data.get("items") or []:
                if it.get("product_id"):
                    product_ids.add(it["product_id"])
        for data in resolution_map.values():
            for it in data.get("items") or []:
                if it.get("product_id"):
                    product_ids.add(it["product_id"])
        products = {p.id: p for p in Product.query.filter(
            Product.id.in_(list(product_ids) or [0])
        ).all()}

        # 5) Orden: pendientes de leer primero; dentro del mismo grupo, la
        #    fecha de la respuesta más reciente primero.
        movements.sort(
            key=lambda m: (
                0 if (notif := notif_map.get(m.id)) and not notif.is_read else 1,
                -(resolution_map[m.id]["resolved_at"] or m.date or datetime.min).timestamp() if (resolution_map[m.id]["resolved_at"] or m.date) else float('-inf'),
            )
        )

        if limit is not None:
            movements = movements[:limit]

        # 6) Adjuntar todo en memoria (sin tocar la base de datos ni el modelo).
        for mov in movements:
            res = resolution_map[mov.id]
            rec = reception_map.get(mov.id, {})
            notif = notif_map.get(mov.id)

            mov.origin_location = locations.get(mov.origin_location_id)
            mov.destination_location = locations.get(mov.destination_location_id)

            # Estado de lectura (servidor). Sin notificación = sin pendiente.
            mov.is_read = True if notif is None else notif.is_read
            mov.notification_id = notif.id if notif else None

            # Datos del dictamen
            mov.response_date = res["resolved_at"]
            mov.response_by = users.get(res["resolved_by_id"])
            mov.resolution_notes = res["notes"] or mov.resolution_notes
            mov.resolution_summary = res["summary"]
            mov.resolution_items = [
                {
                    "product": products.get(it.get("product_id")),
                    "product_id": it.get("product_id"),
                    "lot_number": it.get("lot_number"),
                    "action": it.get("action"),
                    "action_label": RESOLUTION_ACTION_LABELS.get(
                        it.get("action"), (it.get("action") or "SIN_ACCION")
                    ),
                    "credited_qty": it.get("credited_qty"),
                    "return_qty": it.get("return_qty"),
                    "lost_qty": it.get("lost_qty"),
                }
                for it in res["items"]
            ]

            # Datos de la novedad/recepción original
            novelty_type = rec.get("novelty_type")
            received_by = users.get(rec.get("received_by_user_id"))
            mov.novedad_type = novelty_type
            mov.novedad_label = NOVEDAD_LABELS.get(novelty_type) or (
                (novelty_type or '').replace('_', ' ').title() or 'Novedad'
            )
            mov.novedad_items = [
                {
                    "product_name": it.get("product_name"),
                    "sku": it.get("sku"),
                    "lot_number": it.get("lot_number"),
                    "observed_physical_lot": it.get("observed_physical_lot"),
                    "dispatched_qty": it.get("dispatched_qty"),
                    "received_qty": it.get("received_qty"),
                    "missing_qty": it.get("missing_qty"),
                    "specific_novelty": SPECIFIC_NOVELTY_LABELS.get(
                        it.get("specific_novelty"), it.get("specific_novelty")
                    ),
                }
                for it in rec.get("items") or []
            ]
            mov.reported_notes = rec.get("notes") or ""
            mov.reported_by = received_by or users.get(mov.user_id)

        return movements

    @staticmethod
    def mark_as_read(user, movement_id):
        """Marca leída la respuesta de un traslado para el usuario (servidor)."""
        notifications = Notification.query.filter_by(
            user_id=user.id,
            movement_id=movement_id,
            type=RESPONSE_NOTIFICATION_TYPE,
        ).all()
        for notif in notifications:
            if not notif.is_read:
                notif.is_read = True
        db.session.commit()
        return bool(notifications)

    @staticmethod
    def mark_all_as_read(user):
        """Marca todas las respuestas del usuario como leídas."""
        notifications = Notification.query.filter_by(
            user_id=user.id,
            type=RESPONSE_NOTIFICATION_TYPE,
            is_read=False,
        ).all()
        for notif in notifications:
            notif.is_read = True
        db.session.commit()
        return len(notifications)