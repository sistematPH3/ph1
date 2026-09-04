import json
from datetime import datetime
from types import SimpleNamespace

from app.extensions import db
from app.models import AuditLog, Location, Movement, Notification, Product, User
from app.models.security_model import user_locations
from app.models.waste_model import Waste, WasteType, WasteDetail
from sqlalchemy import or_


# Acciones de auditoría que registran la recepción (y su clasificación).
RECEPTION_AUDIT_ACTIONS = (
    'RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD', 'RECEPCION_CONFORME'
)

# Tipo de notificación que representa una respuesta del Administrador.
RESPONSE_NOTIFICATION_TYPE = 'RESPUESTA_TRASLADO'

# Tipos de notificación de la decisión de una merma mayor (aprobada/rechazada).
MERMA_NOTIFICATION_TYPES = ('MERMA_APROBADA', 'MERMA_RECHAZADA')

# Etiqueta legible de cada decisión de merma.
WASTE_DECISION_LABELS = {
    'MERMA_APROBADA': 'Aprobada',
    'MERMA_RECHAZADA': 'Rechazada',
}

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
    def _user_locations_ids(user_id):
        """Ids de las sedes asignadas al usuario (user_locations)."""
        rows = db.session.query(user_locations.c.location_id).filter(
            user_locations.c.user_id == user_id
        ).all()
        return [r[0] for r in rows]

    @staticmethod
    def get_unread_count(user):
        """Cuenta las respuestas pendientes de leer (traslados + mermas)."""
        count = Notification.query.filter_by(
            user_id=user.id,
            type=RESPONSE_NOTIFICATION_TYPE,
            is_read=False,
        ).count()
        for w in ResponseInboxRepository.get_waste_responses(user):
            if not w.is_read:
                count += 1
        return count

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

        if not resolution_map:
            movements = []

        # 5) Adjuntar todo en memoria (sin tocar la base de datos ni el modelo).
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
            mov.response_type = 'TRASLADO'
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

        # 6) Respuestas de mermas (aprobada/rechazada) visibles para el usuario.
        movements.extend(ResponseInboxRepository.get_waste_responses(user))

        # 7) Orden unificado: pendientes de leer primero; dentro del grupo, la
        #    fecha de la respuesta más reciente primero.
        movements.sort(
            key=lambda r: (
                0 if not r.is_read else 1,
                -((r.response_date or datetime.min).timestamp())
                if r.response_date else float('-inf'),
            )
        )

        if limit is not None:
            movements = movements[:limit]

        return movements

    # ------------------------------------------------------------------
    # Respuestas de mermas (aprobada / rechazada)
    # ------------------------------------------------------------------
    @staticmethod
    def get_waste_responses(user):
        """Decisiones de mermas (MERMA_APROBADA / MERMA_RECHAZADA) visibles.

        - Admin / Finanzas: todas las sedes (bandeja global).
        - Otros roles: solo las mermas de las sedes que tienen asignadas
          (aunque no hayan registrado la merma ellos).

        Estado de lectura: una merma se considera NO leída si el usuario no
        tiene todavía una notificación de "leído" para esa decisión (o la
        tiene con is_read=False). Al abrirla / marcarla leída se crea la fila.
        """
        # 0) Notificaciones de decisiones emitidas (fuente de "existe decisión").
        notifs = Notification.query.filter(
            Notification.type.in_(MERMA_NOTIFICATION_TYPES)
        ).all()
        by_waste = {}
        for n in notifs:
            if n.waste_id is None:
                continue
            by_waste.setdefault(n.waste_id, n)

        if not by_waste:
            return []

        is_global = user.is_admin or user.is_finance
        scope_ids = None
        if not is_global:
            scope_ids = set(ResponseInboxRepository._user_locations_ids(user.id))
            if not scope_ids:
                return []

        # Filas de "leído" de este usuario (para marcar pendientes/leídos).
        user_read = {}
        for n in Notification.query.filter_by(user_id=user.id).all():
            if n.type in MERMA_NOTIFICATION_TYPES and n.waste_id is not None:
                user_read[n.waste_id] = n

        # 1) Mermas decididas.
        waste_ids = list(by_waste.keys())
        wastes = {
            w.id: w for w in Waste.query.filter(Waste.id.in_(waste_ids)).all()
        }

        # 2) Catálogo de tipos, sedes y usuarios.
        type_ids = {w.waste_type_id for w in wastes.values() if w.waste_type_id}
        types = {}
        if type_ids:
            types = {
                t.id: t for t in WasteType.query.filter(
                    WasteType.id.in_(list(type_ids))
                ).all()
            }
        locs = {loc.id: loc for loc in Location.query.all()}
        user_ids = set()
        for w in wastes.values():
            user_ids.add(w.user_id)
            if w.approved_by_id:
                user_ids.add(w.approved_by_id)
        users = {}
        if user_ids:
            users = {
                u.id: u for u in User.query.filter(User.id.in_(list(user_ids))).all()
            }

        # 3) Líneas y productos.
        lines_by_waste = {}
        prod_ids = set()
        for d in WasteDetail.query.filter(WasteDetail.waste_id.in_(waste_ids)).all():
            lines_by_waste.setdefault(d.waste_id, []).append({
                'product_id': d.product_id,
                'lot_number': d.lot_number,
                'expiration_date': d.expiration_date,
                'quantity': float(d.quantity or 0),
            })
            prod_ids.add(d.product_id)
        prods = {}
        if prod_ids:
            prods = {
                p.id: p for p in Product.query.filter(Product.id.in_(list(prod_ids))).all()
            }

        # 4) Motivo del rechazo: la razón vive en la auditoría MERMA_RECHAZADA.
        rejection_map = ResponseInboxRepository._waste_rejection_reasons(waste_ids)

        # 5) Armar las respuestas.
        respuestas = []
        for wid, notif in by_waste.items():
            w = wastes.get(wid)
            if not w:
                continue
            # Visibilidad por sede (no-admin).
            if not is_global and w.location_id not in scope_ids:
                continue

            tipo = notif.type
            read_row = user_read.get(wid)
            is_read = bool(read_row and read_row.is_read)
            decision = 'APROBADA' if tipo == 'MERMA_APROBADA' else 'RECHAZADA'
            t = types.get(w.waste_type_id)
            loc = locs.get(w.location_id)

            productos = [{
                'product': prods.get(d['product_id']),
                'product_id': d['product_id'],
                'product_name': (
                    prods.get(d['product_id']).name if prods.get(d['product_id'])
                    else 'Producto N/D'
                ),
                'lot_number': d['lot_number'],
                'expiration_date': d['expiration_date'],
                'quantity': d['quantity'],
            } for d in lines_by_waste.get(wid, [])]

            respuestas.append(SimpleNamespace(
                response_type='MERMA',
                id=w.id,
                waste_id=w.id,
                is_read=is_read,
                notification_id=getattr(read_row, 'id', None),
                date=w.date,
                response_date=w.approved_at or (
                    read_row.created_at if read_row else None
                ) or w.date,
                response_by=users.get(w.approved_by_id),
                reported_by=users.get(w.user_id),
                location_id=w.location_id,
                location=loc,
                origin_location=None,
                destination_location=None,
                origin_location_id=None,
                destination_location_id=None,
                move_id=None,
                waste_type_code=t.code if t else '',
                waste_type_name=t.name if t else 'Sin tipo',
                decision=decision,
                decision_label=WASTE_DECISION_LABELS.get(tipo, decision.title()),
                total_quantity=float(w.total_quantity or 0),
                waste_notes=w.notes or '',
                rejection_reason=rejection_map.get(wid, ''),
                novedad_type=tipo,
                novedad_label=WASTE_DECISION_LABELS.get(tipo, 'Merma'),
                novedad_items=[],
                resolution_summary={},
                resolution_items=[],
                resolution_notes='',
                waste_details=productos,
            ))
        return respuestas

    @staticmethod
    def _waste_rejection_reasons(waste_ids):
        """Razones de rechazo {waste_id: motivo} desde la auditoría de mermas."""
        if not waste_ids:
            return {}
        out = {}
        logs = AuditLog.query.filter(
            AuditLog.action == 'MERMA',
            AuditLog.affected_table == 'waste',
        ).all()
        for log in logs:
            data = ResponseInboxRepository._read_data(log)
            if data.get('event') != 'MERMA_RECHAZADA':
                continue
            wid = data.get('waste_id')
            if wid is None:
                continue
            try:
                wid = int(wid)
            except (TypeError, ValueError):
                continue
            if wid in waste_ids and wid not in out:
                out[wid] = (data.get('motivo_rechazo') or '').strip()
        return out

    @staticmethod
    def _apply_waste_read(user, waste_id, decision):
        """Crea/actualiza la fila de lectura del usuario para una decisión.

        La CANCELACIÓN no es una respuesta administrativa: no fabrica fila.
        """
        if decision == 'CANCELADA':
            return None
        tipo = ('MERMA_APROBADA' if decision == 'APROBADA' else 'MERMA_RECHAZADA')
        existing = Notification.query.filter_by(
            user_id=user.id, waste_id=waste_id, type=tipo,
        ).first()
        if existing:
            existing.is_read = True
            return existing.id
        waste = Waste.query.get(waste_id)
        db.session.add(Notification(
            user_id=user.id,
            location_id=waste.location_id if waste else None,
            waste_id=waste_id,
            type=tipo,
            message=(
                f'Merma #{waste_id} fue '
                f'{("aprobada" if tipo == "MERMA_APROBADA" else "rechazada")} '
                f'por el Administrador.'
            ),
            is_read=True,
        ))
        return None

    @staticmethod
    def mark_waste_as_read(user, waste_id):
        """Marca leída la respuesta de una merma para el usuario (servidor)."""
        waste = Waste.query.get(waste_id)
        if not waste:
            return False
        if not (user.is_admin or user.is_finance):
            scope_ids = set(ResponseInboxRepository._user_locations_ids(user.id))
            if waste.location_id not in scope_ids:
                return False
        decision = {
            'APROBADO': 'APROBADA',
            'RECHAZADO': 'RECHAZADA',
            'CANCELADA': 'CANCELADA',
        }.get(waste.status)
        if decision not in ('APROBADA', 'RECHAZADA', 'CANCELADA'):
            return False
        ResponseInboxRepository._apply_waste_read(user, waste_id, decision)
        db.session.commit()
        return True

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
        """Marca todas las respuestas del usuario como leídas (traslados + mermas)."""
        notifications = Notification.query.filter_by(
            user_id=user.id,
            type=RESPONSE_NOTIFICATION_TYPE,
            is_read=False,
        ).all()
        for notif in notifications:
            notif.is_read = True
        marked_wastes = 0
        for w in ResponseInboxRepository.get_waste_responses(user):
            if not w.is_read:
                ResponseInboxRepository._apply_waste_read(
                    user, w.waste_id, w.decision
                )
                marked_wastes += 1
        db.session.commit()
        return len(notifications) + marked_wastes