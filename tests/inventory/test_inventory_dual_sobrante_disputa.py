# =============================================================================
# REGRESIÓN: SOBRANTE PENDIENTE DE ARBITRAJE EN EL INVENTARIO DUAL
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Un sobrante pendiente (despachado 20, recibido 30) se expone como
#      `disputed_quantity` en el origen y NO como tránsito genérico.
#   2) El detalle por lote muestra lo disponible y el sobrante en disputa por
#      separado, sin descontarlo dos veces.
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
    Inventory, Location, Movement, MovementDetail, Product, Purchase,
    PurchaseDetail, Role, User,
)
from app.inventory.services.inventory_views_service import InventoryViewService
from app.inventory.repositories.inventory_views_repository import (
    InventoryViewRepository,
)


class InventoryDualSobranteDisputaTest(unittest.TestCase):

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

        # El id 1 identifica al Almacén Central en la lógica de lotes.
        central = Location(id=1, name="Almacén Central", state="Caracas")
        sede = Location(id=2, name="La Candelaria", state="Caracas")
        db.session.add_all([central, sede])
        db.session.flush()

        admin = User(
            name="Admin", email="admin.dual@test.com", password_hash="x",
            role_id=rol.id,
        )
        producto = Product(
            name="Tomate", sku="TOM-1", unit_of_measure="kg",
            waste_limit=10, is_active=True,
        )
        db.session.add_all([admin, producto])
        db.session.flush()

        # Estado real tras recibir 30 de una guía de 20: el ORIGEN (Central) ya
        # debitó las 10 extra de su current y las resguardó en transit.
        db.session.add(Inventory(
            location_id=central.id, product_id=producto.id,
            current_quantity=Decimal("70.00"),
            reserved_quantity=Decimal("0.00"),
            transit_quantity=Decimal("10.00"),
            min_stock=Decimal("5.00"),
        ))
        movimiento = Movement(
            type="DESPACHO", origin_location_id=central.id,
            destination_location_id=sede.id, status="SOBRANTE_EXCEDENTE",
            user_id=admin.id,
        )
        db.session.add(movimiento)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=movimiento.id, product_id=producto.id,
            lot_number="L-1", quantity=Decimal("20.00"),
            received_quantity=Decimal("30.00"),
            missing_quantity=Decimal("0.00"),
        ))
        compra = Purchase(
            invoice_url="test.pdf", user_id=admin.id, status="COMPLETED",
        )
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=producto.id,
            lot_number="L-1", quantity=Decimal("100.00"),
        ))
        db.session.commit()
        return admin, central, producto

    def _client(self, admin):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["_user_id"] = str(admin.id)
            sesion["_fresh"] = True
        return cliente

    def test_sobrante_pendiente_se_muestra_en_disputa_y_no_en_transito(self):
        admin, central, producto = self._seed()

        contexto = InventoryViewService.get_inventory_for_user(
            admin, {"location_id": central.id}
        )
        item = contexto["inventory"][0]
        self.assertEqual(item.disputed_quantity, Decimal("10"))
        self.assertEqual(item.return_transit_quantity, Decimal("0"))

        respuesta = self._client(admin).get(
            f"/inventory/api/list?location_id={central.id}"
        )
        self.assertEqual(respuesta.status_code, 200)
        fila = respuesta.get_json()["items"][0]
        self.assertEqual(fila["disputed_quantity"], 10.0)
        self.assertEqual(fila["normal_transit_quantity"], 0.0)

        self.assertEqual(
            InventoryViewRepository.get_disputed_qty_by_lot(
                central.id, producto.id
            ),
            {"L-1": 10.0},
        )

        html = self._client(admin).get(
            f"/inventory/views?location_id={central.id}"
        ).data
        self.assertIn("en disputa".encode(), html)
        self.assertNotIn("en tránsito".encode(), html)

        # El detalle por lote refleja lo disponible y expone el sobrante en
        # disputa por separado, sin descontarlo dos veces.
        lotes = InventoryViewService.get_lots_for_product(central.id, producto.id)
        lote = next(l for l in lotes if l["lot_number"] == "L-1")
        self.assertEqual(lote["quantity"], 70.0)
        self.assertEqual(lote["frozen_disputed_quantity"], 10.0)
        self.assertEqual(lote["frozen_transit_quantity"], 0.0)
        self.assertEqual(lote["return_transit_quantity"], 0.0)
        self.assertEqual(lote["retained_incoming_quantity"], 0.0)
        self.assertEqual(lote["frozen_quantity"], 10.0)


if __name__ == "__main__":
    unittest.main()
