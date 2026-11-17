# =============================================================================
# REGRESIÓN: INVENTARIO MULTISEDE SEGÚN EL ROL DEL USUARIO
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Un usuario NO administrador ve consolidadas TODAS sus sedes asignadas,
#      no solo la primera (antes se filtraba por `assigned_locations[0]`).
#   2) Ningún rol distinto de administrador ve el Almacén Central aunque lo
#      tenga asignado.
#   3) El filtro `location_id` solo se respeta dentro del ámbito del usuario.
#   4) El administrador sigue viendo el Central y todas las sedes activas.
# =============================================================================

import os
import unittest
from decimal import Decimal

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test",
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

from app import create_app, db
from app.models import Inventory, Location, Product, Role, User
from app.inventory.services.inventory_views_service import InventoryViewService


class InventoryViewsMultisedeTest(unittest.TestCase):

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

    def _seed(self):
        rol_admin = Role(name="Administrator")
        rol_ops = Role(name="Operations")
        db.session.add_all([rol_admin, rol_ops])
        db.session.flush()

        central = Location(id=1, name="Central", state="Caracas")
        sede_a = Location(id=2, name="Sede A", state="Caracas")
        sede_b = Location(id=3, name="Sede B", state="Miranda")
        sede_ajena = Location(id=4, name="Sede Ajena", state="Aragua")
        db.session.add_all([central, sede_a, sede_b, sede_ajena])
        db.session.flush()

        tomate = Product(name="Tomate", sku="TOM-MS", unit_of_measure="kg", is_active=True)
        queso = Product(name="Queso", sku="QUE-MS", unit_of_measure="kg", is_active=True)
        harina = Product(name="Harina", sku="HAR-MS", unit_of_measure="kg", is_active=True)
        db.session.add_all([tomate, queso, harina])
        db.session.flush()

        db.session.add_all([
            Inventory(location_id=central.id, product_id=tomate.id,
                      current_quantity=Decimal("500.00"), min_stock=Decimal("10.00")),
            Inventory(location_id=sede_a.id, product_id=tomate.id,
                      current_quantity=Decimal("30.00"), min_stock=Decimal("5.00")),
            Inventory(location_id=sede_a.id, product_id=queso.id,
                      current_quantity=Decimal("12.00"), min_stock=Decimal("5.00")),
            Inventory(location_id=sede_b.id, product_id=harina.id,
                      current_quantity=Decimal("40.00"), min_stock=Decimal("5.00")),
            Inventory(location_id=sede_ajena.id, product_id=tomate.id,
                      current_quantity=Decimal("99.00"), min_stock=Decimal("5.00")),
        ])

        admin = User(name="Admin", email="admin@ms.com", password_hash="x",
                     role=rol_admin)
        operador = User(name="Operador", email="ops@ms.com", password_hash="x",
                        role=rol_ops, locations=[sede_a, sede_b, central])
        db.session.add_all([admin, operador])
        db.session.commit()

        return {
            "admin": admin, "operador": operador,
            "central": central, "sede_a": sede_a, "sede_b": sede_b,
            "sede_ajena": sede_ajena, "tomate": tomate, "queso": queso,
            "harina": harina,
        }

    def _sedes(self, contexto):
        return {item.location_id for item in contexto["inventory"]}

    def test_no_admin_consolida_todas_sus_sedes(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(env["operador"], {})

        self.assertFalse(contexto["is_admin"])
        self.assertEqual(self._sedes(contexto), {env["sede_a"].id, env["sede_b"].id})
        # Consolidado: los tres insumos de sus sedes, sin la sede ajena.
        self.assertEqual(len(contexto["inventory"]), 3)
        self.assertIsNone(contexto["selected_location_id"])
        self.assertIn("Todas tus sedes", contexto["assigned_location_name"])

    def test_no_admin_no_ve_el_almacen_central(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(
            env["operador"], {"location_id": env["central"].id}
        )

        # El filtro por Central se ignora: no está en su ámbito.
        self.assertNotIn(env["central"].id, self._sedes(contexto))
        self.assertEqual(self._sedes(contexto), {env["sede_a"].id, env["sede_b"].id})
        self.assertNotIn(env["central"].id, [l.id for l in contexto["available_locations"]])

    def test_no_admin_puede_filtrar_una_de_sus_sedes(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(
            env["operador"], {"location_id": env["sede_b"].id}
        )

        self.assertEqual(self._sedes(contexto), {env["sede_b"].id})
        self.assertEqual(contexto["selected_location_id"], env["sede_b"].id)
        self.assertEqual(contexto["assigned_location_name"], "Sede B")

    def test_no_admin_no_puede_filtrar_sede_ajena(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(
            env["operador"], {"location_id": env["sede_ajena"].id}
        )

        self.assertNotIn(env["sede_ajena"].id, self._sedes(contexto))
        self.assertEqual(self._sedes(contexto), {env["sede_a"].id, env["sede_b"].id})

    def test_admin_ve_central_y_todas_las_sedes(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(
            env["admin"], {"location_id": env["central"].id}
        )

        self.assertTrue(contexto["is_admin"])
        self.assertEqual(self._sedes(contexto), {env["central"].id})
        self.assertEqual(
            {l.id for l in contexto["available_locations"]},
            {env["central"].id, env["sede_a"].id, env["sede_b"].id, env["sede_ajena"].id},
        )

    def test_admin_sin_filtro_mantiene_vista_por_sede_y_ofrece_toda_la_red(self):
        env = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(env["admin"], {})

        # El administrador conserva la vista por sede (elige en el listado)…
        self.assertEqual(len(self._sedes(contexto)), 1)
        self.assertIn(contexto["selected_location_id"], self._sedes(contexto))
        # …pero el listado le ofrece el Central y todas las sedes activas.
        self.assertEqual(
            {l.id for l in contexto["available_locations"]},
            {env["central"].id, env["sede_a"].id, env["sede_b"].id, env["sede_ajena"].id},
        )


    def test_vista_renderiza_el_consolidado_para_no_admin(self):
        env = self._seed()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["_user_id"] = str(env["operador"].id)
            sesion["_fresh"] = True

        respuesta = cliente.get("/inventory/views")

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b"Todas tus sedes", respuesta.data)
        self.assertIn(b"Sede A", respuesta.data)
        self.assertIn(b"Sede B", respuesta.data)
        self.assertNotIn(b"Sede Ajena", respuesta.data)


if __name__ == "__main__":
    unittest.main()
