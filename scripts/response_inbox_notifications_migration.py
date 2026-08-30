# =============================================================================
# MIGRACION + BACKFILL DE LA BANDEJA DE RESPUESTAS (tabla notifications)
# -----------------------------------------------------------------------------
# Hace tres cosas sobre la base de datos REAL (ph):
#   1. Asegura la columna notifications.movement_id (idempotente).
#   2. Crea el indice unico (user_id, movement_id, type) (idempotente).
#   3. Backfill: crea una Notification de tipo RESPUESTA_TRASLADO por cada
#      traslado ya resuelto, para los destinatarios que correspondan, marcada
#      como NO LEIDA (is_read=False) para que cada usuario la vea "nueva" y
#      al abrirla se marque leida en el servidor.
#
# Uso (en la carpeta ph1):
#   .\.venv\Scripts\python.exe scripts\response_inbox_notifications_migration.py
#   .\.venv\Scripts\python.exe scripts\response_inbox_notifications_migration.py --reset-unread
#     -> Ademas, revierte a NO LEIDA las notificaciones de respuesta ya creadas,
#        para que los mensajes antiguos vuelvan a verse como nuevos.
# Puede apuntar a otra base con la variable de entorno DATABASE_URL.
# =============================================================================

import os
import sys

from sqlalchemy import text

# Asegurar que los imports de la app funcionen desde scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import AuditLog, Location, Movement, Notification, Role, User

RESPONSE_TYPE = 'RESPUESTA_TRASLADO'


def ensure_schema():
    """Columna movement_id + indice unico (idempotente)."""
    with db.engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS movement_id integer"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_user_movement_type "
            "ON notifications (user_id, movement_id, type)"
        ))
    print("Schema OK: movement_id + unique index listos.")


def recipients_for(movement, resolver_user_id):
    """Mismos destinatarios que _notify_response_resolved del servicio.
    Incluye al usuario que emitió el dictamen: los admin/finanzas ven TODO,
    aunque la respuesta la hayan resuelto ellos mismos."""
    location_ids = {movement.origin_location_id, movement.destination_location_id}
    location_ids.discard(None)

    recipients = {}
    if location_ids:
        for user in User.query.filter(
            User.locations.any(Location.id.in_(location_ids))
        ).all():
            recipients[user.id] = user
    for user in User.query.filter(
        User.role.has(Role.name.in_(['Administrator', 'Finance']))
    ).all():
        recipients[user.id] = user
    return recipients


def backfill():
    # Resoluciones existentes, de la mas antigua a la mas reciente.
    logs = (
        AuditLog.query
        .filter(AuditLog.action == 'RESOLUCION_DISPUTA')
        .order_by(AuditLog.timestamp.asc())
        .all()
    )

    created = 0
    skipped = 0
    for log in logs:
        data = log.changed_data
        if isinstance(data, str):
            import json
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                continue
        mov_id = data.get('movement_id') if isinstance(data, dict) else None
        if mov_id is None:
            continue
        movement = Movement.query.get(int(mov_id))
        if movement is None:
            skipped += 1
            continue

        resolver = log.user_id
        for uid, user in recipients_for(movement, resolver).items():
            existing = Notification.query.filter_by(
                user_id=uid, movement_id=movement.id, type=RESPONSE_TYPE
            ).first()
            if existing is not None:
                skipped += 1
                continue
            user_loc_ids = {loc.id for loc in user.locations}
            loc_id = None
            if movement.destination_location_id in user_loc_ids:
                loc_id = movement.destination_location_id
            elif movement.origin_location_id in user_loc_ids:
                loc_id = movement.origin_location_id
            db.session.add(Notification(
                user_id=uid,
                location_id=loc_id,
                type=RESPONSE_TYPE,
                message=f"Respuesta del Administrador · Traslado #{movement.id}",
                is_read=False,  # aparece "nueva" hasta que el usuario la abra
                movement_id=movement.id,
                created_at=log.timestamp or movement.date,
            ))
            created += 1

    db.session.commit()
    print(f"Backfill OK: {created} notificaciones creadas, {skipped} omitidas.")


def reset_unread():
    """Revierte a 'no leida' las notificaciones de respuesta ya creadas, para
    que los mensajes antiguos vuelvan a verse como nuevos en la bandeja."""
    rows = Notification.query.filter_by(
        type=RESPONSE_TYPE, is_read=True
    ).all()
    for n in rows:
        n.is_read = False
    db.session.commit()
    print(f"Reset unread OK: {len(rows)} notificaciones revueltas a NO LEIDAS.")


if __name__ == "__main__":
    reset = "--reset-unread" in sys.argv
    app = create_app()
    with app.app_context():
        ensure_schema()
        backfill()
        if reset:
            reset_unread()
    print("Listo.")