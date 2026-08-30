# =============================================================================
# PRUEBA DEL RESUMEN EN VIVO DE NOVEDADES (BADGE DEL SIDEBAR + AVISOS)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) get_pending_disputes_count() cuenta solo las novedades sin resolver.
#   2) get_dispute_notifications_summary() devuelve el JSON que alimenta el
#      círculo rojo del sidebar y los avisos emergentes del dashboard.
#   3) Un movimiento en estado COMPLETADO (ya resuelto) NO aparece pendiente.
#
# Cómo funciona:
#   - Usa la base DE PRUEBA (ph_test), nunca la base real (ph).
#   - Para ejecutarla, en la carpeta ph1:
#       .\.venv\Scripts\python.exe -m unittest tests/logistics/test_dispute_notifications.py -v
# =============================================================================

import os
import unittest

from sqlalchemy import create_engine, text

# Base de datos de pruebas (puedes cambiar la URL con una variable TEST_DATABASE_URL).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _ensure_test_database_exists():
    """Crea la base ph_test si aún no existe (conexión al motor postgres)."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


# IMPORTANTE: esto DEBE correr antes de importar la app, porque la app lee la
# variable DATABASE_URL en el arranque. Apuntamos a la base de pruebas.
_ensure_test_database_exists()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db
from app.models import AuditLog, Location, Movement, MovementDetail, Product, Role, User
from app.logistics.services.movement_dispute_service import (
    get_pending_disputes_count,
    get_dispute_notifications_summary,
)


class DisputeNotificationsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Una sola vez: crea la app y las tablas en ph_test."""
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        """Cada prueba arranca con el contexto de la app y sin datos."""
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        """Cada prueba termina borrando TODO lo que se creó (base limpia)."""
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # =========================================================================
    # AYUDA: crea un movimiento-fantasma con auditoría de recepción.
    # =========================================================================
    def _seed_dispute(self, status="FALTANTE_CONTEO", movement_id_bias=0):
        loc_origin = Location(name="Sede Origen", state="Caracas")
        loc_dest = Location(name="Sede Destino", state="Caracas")
        product = Product(name="Tomate", sku="TOM-%s%s" % (status, movement_id_bias))
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Admin Test", email="notif-%s%s@test.com" % (status, movement_id_bias),
                    password_hash="x", role_id=role.id)
        db.session.add_all([loc_origin, loc_dest, product, user])
        db.session.flush()

        mov = Movement(
            type="TRASLADO",
            origin_location_id=loc_origin.id,
            destination_location_id=loc_dest.id,
            status=status,
            user_id=user.id
        )
        db.session.add(mov)
        db.session.flush()

        detail = MovementDetail(
            movement_id=mov.id,
            product_id=product.id,
            lot_number="L-001",
            quantity=10,
            received_quantity=8,
            missing_quantity=2
        )
        db.session.add(detail)
        db.session.flush()

        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_NOVEDAD",
            severity="ALERTA",
            user_id=user.id,
            location_id=loc_dest.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RECEPCION_NOVEDAD",
                "notes": "Novedad registrada en muelle",
                "erroneous_products_delivered": [],
                "discrepancies": [{
                    "product_id": product.id,
                    "type": "FALTANTE",
                    "authorized_qty": 10.0,
                    "physical_received_qty": 8.0,
                    "extra_units": 0.0,
                    "notes": "Faltan 2"
                }]
            }
        ))
        db.session.commit()
        return mov, loc_origin, loc_dest

    # =========================================================================
    # CASO 1: el conteo refleja solo las novedades realmente pendientes.
    # =========================================================================
    def test_count_solo_novedades_pendientes(self):
        self._seed_dispute(status="FALTANTE_CONTEO")
        self._seed_dispute(status="SOBRANTE_EXCEDENTE")

        # Un movimiento resuelto (COMPLETADO) no debe contarse.
        mov_resuelto, _, _ = self._seed_dispute(status="LOTE_NO_COINCIDE")
        mov_resuelto.status = "COMPLETADO"
        db.session.commit()

        self.assertEqual(get_pending_disputes_count(), 2)

    # =========================================================================
    # CASO 2: el resumen trae los datos que alimentan badge y avisos.
    # =========================================================================
    def test_summary_incluye_items_y_pending_count(self):
        mov, origin, dest = self._seed_dispute(status="FALTANTE_CONTEO")

        summary = get_dispute_notifications_summary()

        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(len(summary["items"]), 1)

        item = summary["items"][0]
        self.assertEqual(item["id"], mov.id)
        self.assertEqual(item["status"], "FALTANTE_CONTEO")
        self.assertEqual(item["status_label"], "Faltante de Conteo")
        self.assertEqual(item["origin"], origin.name)
        self.assertEqual(item["destination"], dest.name)
        self.assertIsNotNone(item["notification_date"])

        base_ts = item["notification_date"]
        self.assertEqual(summary["last_seen_date"], base_ts)

    # =========================================================================
    # CASO 3: el límite recorta el número de ítems, el conteo total se mantiene.
    # =========================================================================
    def test_summary_respeta_limite(self):
        self._seed_dispute(status="FALTANTE_CONTEO", movement_id_bias=1)
        self._seed_dispute(status="SOBRANTE_EXCEDENTE", movement_id_bias=2)
        self._seed_dispute(status="PRODUCTO_ERRONEO", movement_id_bias=3)

        summary_limit_2 = get_dispute_notifications_summary(limit=2)

        self.assertEqual(summary_limit_2["pending_count"], 3)
        self.assertEqual(len(summary_limit_2["items"]), 2)

    # =========================================================================
    # CASO 4: sin novedades, el resumen vuelve vacío (badge oculto).
    # =========================================================================
    def test_summary_vacio_cuando_no_hay_pendientes(self):
        summary = get_dispute_notifications_summary()
        self.assertEqual(summary["pending_count"], 0)
        self.assertEqual(summary["items"], [])
        self.assertIsNone(summary["last_seen_date"])


if __name__ == "__main__":
    unittest.main()