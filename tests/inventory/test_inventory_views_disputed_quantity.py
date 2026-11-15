# =============================================================================
# REGRESIÓN: INVENTARIO DUAL CON FALTANTE EN DISPUTA
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) El servicio expone `disputed_quantity` como Decimal (no float crudo),
#      porque `transit_quantity` del modelo es Decimal.
#   2) La vista /inventory/views renderiza sin el error
#      "unsupported operand type(s) for -: 'decimal.Decimal' and 'float'"
#      cuando hay tránsito normal y faltante en disputa a la vez.
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
from app.models import (
    Inventory, Location, Movement, MovementDetail, Product, Role, User,
)
from app.inventory.services.inventory_views_service import InventoryViewService


class InventoryViewsDisputedQuantityTest(unittest.TestCase):

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
        rol = Role(name="Administrator")
        db.session.add(rol)
        db.session.flush()

        sede = Location(name="Sede Central", state="Caracas")
        db.session.add(sede)
        db.session.flush()

        admin = User(
            name="Admin", email="admin@test.com", password_hash="x",
            role_id=rol.id,
        )
        producto = Product(
            name="Tomate", sku="TOM-1", unit_of_measure="kg",
            waste_limit=10, is_active=True,
        )
        db.session.add_all([admin, producto])
        db.session.flush()

        db.session.add(Inventory(
            location_id=sede.id, product_id=producto.id,
            current_quantity=Decimal("100.00"),
            reserved_quantity=Decimal("0.00"),
            transit_quantity=Decimal("10.00"),
            min_stock=Decimal("5.00"),
        ))

        # Traslado con novedad abierta: 4 unidades faltantes siguen en disputa.
        movimiento = Movement(
            type="TRASLADO", origin_location_id=sede.id,
            destination_location_id=sede.id, status="NOVEDAD_FALTANTE",
            user_id=admin.id,
        )
        db.session.add(movimiento)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=movimiento.id, product_id=producto.id,
            lot_number="L-1", quantity=10, received_quantity=6,
            missing_quantity=4,
        ))
        db.session.commit()
        return admin, sede, producto

    def test_servicio_expone_disputa_como_decimal(self):
        admin, sede, _ = self._seed()
        contexto = InventoryViewService.get_inventory_for_user(
            admin, {"location_id": sede.id}
        )
        item = contexto["inventory"][0]
        self.assertIsInstance(item.disputed_quantity, Decimal)
        self.assertEqual(item.disputed_quantity, Decimal("4"))

    def test_vista_renderiza_sin_mezclar_decimal_y_float(self):
        admin, sede, _ = self._seed()
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["_user_id"] = str(admin.id)
            sesion["_fresh"] = True

        respuesta = cliente.get(f"/inventory/views?location_id={sede.id}")

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b"en disputa", respuesta.data)


if __name__ == "__main__":
    unittest.main()
