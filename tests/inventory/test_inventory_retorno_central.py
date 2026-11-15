# =============================================================================
# REGRESIÓN: RETORNO HACIA CENTRAL EN EL INVENTARIO DUAL
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) La sede que devuelve no muestra las unidades como tránsito genérico:
#      se exponen como devolución al central.
#   2) El Central las refleja como retenidas por recibir, sin alterar su stock
#      disponible hasta la recepción física en muelle.
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


class InventoryRetornoCentralTest(unittest.TestCase):

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

        central = Location(id=1, name="Almacén Central", state="Caracas")
        sede = Location(id=2, name="La Candelaria", state="Caracas")
        db.session.add_all([central, sede])
        db.session.flush()

        admin = User(
            name="Admin", email="admin.retorno@test.com", password_hash="x",
            role_id=rol.id,
        )
        producto = Product(
            name="Tomate", sku="TOM-1", unit_of_measure="kg",
            waste_limit=10, is_active=True,
        )
        db.session.add_all([admin, producto])
        db.session.flush()

        db.session.add_all([
            Inventory(
                location_id=sede.id, product_id=producto.id,
                current_quantity=Decimal("90.00"),
                reserved_quantity=Decimal("0.00"),
                transit_quantity=Decimal("10.00"),
                min_stock=Decimal("5.00"),
            ),
            Inventory(
                location_id=central.id, product_id=producto.id,
                current_quantity=Decimal("100.00"),
                reserved_quantity=Decimal("0.00"),
                transit_quantity=Decimal("0.00"),
                min_stock=Decimal("5.00"),
            ),
        ])
        retorno = Movement(
            type="RETORNO_EMERGENCIA", origin_location_id=sede.id,
            destination_location_id=central.id, status="EN_TRANSITO",
            user_id=admin.id,
        )
        db.session.add(retorno)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=retorno.id, product_id=producto.id,
            lot_number="L-1", quantity=Decimal("10.00"),
            missing_quantity=Decimal("0.00"),
        ))
        db.session.commit()
        return admin, central, sede, producto

    def _client(self, admin):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["_user_id"] = str(admin.id)
            sesion["_fresh"] = True
        return cliente

    def _api_item(self, cliente, location_id):
        respuesta = cliente.get(f"/inventory/api/list?location_id={location_id}")
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertTrue(datos["success"])
        return datos["items"][0]

    def test_retorno_no_es_transito_de_la_sede_y_queda_retenido_en_central(self):
        admin, central, sede, producto = self._seed()
        cliente = self._client(admin)

        origen = self._api_item(cliente, sede.id)
        self.assertEqual(origen["return_transit_quantity"], 10.0)
        self.assertEqual(origen["normal_transit_quantity"], 0.0)
        self.assertEqual(origen["retained_incoming_quantity"], 0.0)

        destino = self._api_item(cliente, central.id)
        self.assertEqual(destino["retained_incoming_quantity"], 10.0)
        self.assertEqual(destino["normal_transit_quantity"], 0.0)
        # Las unidades aún no están disponibles en Central.
        self.assertEqual(destino["available_quantity"], 100.0)

        html_sede = cliente.get(f"/inventory/views?location_id={sede.id}").data
        self.assertIn("en devolución al central".encode(), html_sede)

        html_central = cliente.get(
            f"/inventory/views?location_id={central.id}"
        ).data
        self.assertIn("retenidos por recibir".encode(), html_central)

        # El detalle por lote debe incluir partidas que solo existen por la
        # devolución (no tienen entrada conforme en la sede).
        lotes_sede = InventoryViewService.get_lots_for_product(sede.id, producto.id)
        self.assertEqual(len(lotes_sede), 1)
        lote_sede = lotes_sede[0]
        self.assertEqual(lote_sede["lot_number"], "L-1")
        self.assertEqual(lote_sede["quantity"], 0.0)
        self.assertEqual(lote_sede["return_transit_quantity"], 10.0)
        self.assertEqual(lote_sede["retained_incoming_quantity"], 0.0)
        self.assertEqual(lote_sede["frozen_transit_quantity"], 0.0)

        lotes_central = InventoryViewService.get_lots_for_product(
            central.id, producto.id
        )
        self.assertEqual(len(lotes_central), 1)
        lote_central = lotes_central[0]
        self.assertEqual(lote_central["quantity"], 0.0)
        self.assertEqual(lote_central["retained_incoming_quantity"], 10.0)
        self.assertEqual(lote_central["return_transit_quantity"], 0.0)
        self.assertEqual(lote_central["frozen_transit_quantity"], 0.0)


if __name__ == "__main__":
    unittest.main()
