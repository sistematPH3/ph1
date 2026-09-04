# =============================================================================
# PRUEBA AUTOMÁTICA DE LA BANDEJA DE APROBACIÓN DE MERMAS (Parte 3 + Parte 5)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Aprobar una merma PENDIENTE descuenta stock (current_quantity), marca
#      APROBADO, crea auditoría NORMAL (event MERMA_APROBADA) y notifica al autor.
#   2) Aprobar exige rol Administrador (otro rol -> PermissionError).
#   3) Aprobar una merma no-pendiente se rechaza sin tocar stock.
#   4) Aprobar con stock insuficiente se aborta sin descontar nada.
#   5) Rechazar una merma PENDIENTE NO toca stock, marca RECHAZADO, crea
#      auditoría ALERTA (event MERMA_RECHAZADA) y notifica al autor.
#   6) La cola de pendientes filtra por sede según el usuario.
#   7) El detalle devuelve líneas con nombre de producto y stock del lote.
#
# Uso (en la carpeta ph1, Linux/Ubuntu):
#   .venv/bin/python -m unittest tests.waste.test_merma_approvals -v
# =============================================================================

import os
import unittest
import json
from datetime import datetime

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _ensure_test_database_exists():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_ensure_test_database_exists()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db  # noqa: E402
from app.models import (  # noqa: E402
    Inventory, Location, Product, Role, User,
    Waste, WasteDetail, WasteType, AuditLog,
)
from app.models.security_model import Notification  # noqa: E402
from app.waste.services import merma_approvals_service as svc  # noqa: E402


class MermaApprovalsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _seed(self, stock=100.0, qty=10.0):
        """Admin, autor (Operations) y una merma PENDIENTE en una sede."""
        role_admin = Role(name="Administrator")
        role_ops = Role(name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        admin = User(name="Admin", email="admin@test.com",
                     password_hash="x", role_id=role_admin.id)
        author = User(name="Cocinera", email="cocina@test.com",
                      password_hash="x", role_id=role_ops.id)
        loc = Location(name="Sede Test", state="Caracas")
        product = Product(name="Tomate", sku="TOM-W1", unit_of_measure="kg")
        db.session.add_all([admin, author, loc, product])
        db.session.flush()

        inv = Inventory(
            location_id=loc.id, product_id=product.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20
        )
        db.session.add(inv)
        wt = WasteType(name="Vencido", requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc.id, waste_type_id=wt.id, user_id=author.id,
            status="PENDIENTE", total_quantity=qty, notes="Merma de prueba",
            date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-AAA",
            expiration_date=None, quantity=qty, unit_cost=1.0, subtotal_cost=qty,
        ))
        db.session.commit()

        return {
            "admin": admin, "author": author, "loc": loc, "product": product,
            "inventory": inv, "waste": waste, "waste_type": wt,
        }

    # =========================================================================
    # CASO 1: APROBAR -> descuenta stock + APROBADO + auditoría + notificación
    # =========================================================================
    def test_aprobar_descuenta_stock_y_audita(self):
        env = self._seed(stock=100.0, qty=10.0)

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertTrue(res["success"], res)

        db.session.refresh(env["inventory"])
        db.session.refresh(env["waste"])
        self.assertEqual(float(env["inventory"].current_quantity), 90.0)
        self.assertEqual(env["waste"].status, "APROBADO")
        self.assertEqual(env["waste"].approved_by_id, env["admin"].id)
        self.assertIsNotNone(env["waste"].approved_at)

        audit = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.severity, "NORMAL")
        self.assertEqual(audit.user_id, env["admin"].id)
        self.assertEqual(audit.location_id, env["loc"].id)
        changed = json.loads(audit.changed_data) if isinstance(audit.changed_data, str) else audit.changed_data
        self.assertEqual(changed.get("event"), "MERMA_APROBADA")
        self.assertEqual(changed["descuentos_stock"][0]["stock_antes"], 100.0)

        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_APROBADA"
        ).first()
        self.assertIsNotNone(notif)

    # =========================================================================
    # CASO 2: NO-ADMIN NO PUEDE APROBAR
    # =========================================================================
    def test_no_admin_no_puede_aprobar(self):
        env = self._seed()
        with self.assertRaises(PermissionError):
            svc.approve_waste(env["waste"].id, env["author"].id)
        db.session.rollback()

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)

    # =========================================================================
    # CASO 3: APROBAR UNA MERMA NO-PENDIENTE SE RECHAZA
    # =========================================================================
    def test_aprobar_merma_no_pendiente_se_rechaza(self):
        env = self._seed()
        env["waste"].status = "RECHAZADO"
        db.session.commit()

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertFalse(res["success"])
        self.assertIn("pendientes", res["message"])

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)

    # =========================================================================
    # CASO 4: STOCK INSUFICIENTE -> aborta sin descontar
    # =========================================================================
    def test_stock_insuficiente_aborta(self):
        env = self._seed(stock=5.0, qty=10.0)

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertFalse(res["success"])
        self.assertIn("Stock insuficiente", res["message"])

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 5.0)
        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "PENDIENTE")

    # =========================================================================
    # CASO 5: RECHAZAR -> NO toca stock + RECHAZADO + auditoría + notificación
    # =========================================================================
    def test_rechazar_no_toca_stock_y_audita(self):
        env = self._seed(stock=100.0, qty=10.0)

        res = svc.reject_waste(env["waste"].id, env["admin"].id, "Merma inválida, no corresponde.")
        self.assertTrue(res["success"], res)

        db.session.refresh(env["inventory"])
        db.session.refresh(env["waste"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)
        self.assertEqual(env["waste"].status, "RECHAZADO")

        audit = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.severity, "ALERTA")
        changed = json.loads(audit.changed_data) if isinstance(audit.changed_data, str) else audit.changed_data
        self.assertEqual(changed.get("event"), "MERMA_RECHAZADA")
        self.assertIn("Merma inválida", changed["motivo_rechazo"])

        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_RECHAZADA"
        ).first()
        self.assertIsNotNone(notif)

    # =========================================================================
    # CASO 6: COLA DE PENDIENTES FILTRA POR SEDE
    # =========================================================================
    def test_cola_pendientes_filtra_por_sede(self):
        env = self._seed()

        # Admin ve la pendiente.
        admin_pending = svc.get_pending_wastes(env["admin"].id)
        self.assertEqual(len(admin_pending), 1)
        self.assertEqual(admin_pending[0]["id"], env["waste"].id)

        # Autor (Operations) sin sede asignada no la ve.
        author_pending = svc.get_pending_wastes(env["author"].id)
        self.assertEqual(author_pending, [])

    # =========================================================================
    # CASO 7: DETALLE DEVUELVE LÍNEAS CON PRODUCTO Y STOCK DEL LOTE
    # =========================================================================
    def test_detalle_con_lineas_y_stock_de_lote(self):
        env = self._seed(stock=100.0, qty=10.0)

        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        self.assertEqual(data["id"], env["waste"].id)
        self.assertEqual(data["location_name"], "Sede Test")
        self.assertEqual(len(data["lines"]), 1)
        line = data["lines"][0]
        self.assertEqual(line["product_name"], "Tomate")
        self.assertEqual(line["lot_number"], "L-AAA")
        self.assertEqual(line["quantity"], 10.0)
        # El lote tiene stock(100) - consumo(0) = 100.
        self.assertEqual(line["stock_en_lote"], 100.0)

    # =========================================================================
    # CASO 8: DETALLE INCLUYE LÍMITE DE MERMA DEL PRODUCTO
    # =========================================================================
    def test_detalle_incluye_limite_de_merma(self):
        env = self._seed(stock=100.0, qty=10.0)
        env["product"].waste_limit = 8.0
        db.session.commit()

        # Merma 10 > límite 8 -> excede.
        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        line = data["lines"][0]
        self.assertEqual(line["waste_limit"], 8.0)
        self.assertTrue(line["excede_limite"])

        # Producto sin límite -> None y no excede (misma merma/pedido).
        env["product"].waste_limit = None
        db.session.commit()
        data2, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        line2 = data2["lines"][0]
        self.assertIsNone(line2["waste_limit"])
        self.assertFalse(line2["excede_limite"])


if __name__ == "__main__":
    unittest.main()
