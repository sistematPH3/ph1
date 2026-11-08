# =============================================================================
# PRUEBA AUTOMÁTICA DEL MÍNIMO DE STOCK CONFIGURABLE POR PRODUCTO
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Al crear un insumo con min_stock se guarda y aplica (en la unidad del
#      producto: si la unidad es KG, 15 = 15 kilogramos).
#   2) Al crear sin min_stock, el efectivo es 20 (default).
#   3) Al editar el insumo, el mínimo se propaga a los inventarios existentes
#      de todas las sedes.
#   4) La auto-creación de inventario usa el mínimo del producto (vía
#      _get_or_create_inventory, el mismo patrón de compras/traslados).
#   5) END-TO-END: al registrar una COMPRA por el flujo real, el inventario que
#      se crea toma el mínimo del producto (o 20 si el insumo no lo define).
#   6) El validador del formulario rechaza negativos y acepta vacío.
#
# Uso (en la carpeta ph1):
#   .venv/Scripts/python -m unittest tests.inventory.test_product_min_stock -v
# =============================================================================

import os
import unittest
from decimal import Decimal

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

from app import create_app, db
from app.models import Inventory, Location, Product, Role, Supplier, User
from app.inventory.services.products_service import ProductService
from app.inventory.requests.products_request import validate_product_form
from app.logistics.services.movement_dispute_service import _get_or_create_inventory
from app.logistics.repositories.movement_reception_repository import MovementReceptionRepository
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard
from app.logistics.services.purchase_service import PurchaseService
from flask_login import login_user


class ProductMinStockTest(unittest.TestCase):

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

    def _make(self, min_stock):
        ProductService.create_product({
            "name": "Harina",
            "sku": "HAR-1",
            "product_type_id": None,
            "unit_of_measure": "KG",
            "technical_description": "",
            "waste_limit": "",
            "min_stock": min_stock,
        })

    def test_crear_con_min_stock(self):
        self._make("15")
        p = Product.query.filter_by(sku="HAR-1").one()
        self.assertEqual(p.min_stock, Decimal("15.00"))
        self.assertEqual(p.min_stock_efectivo, Decimal("15.00"))

    def test_crear_sin_min_stock_usa_default_20(self):
        self._make("")
        p = Product.query.filter_by(sku="HAR-1").one()
        self.assertIsNone(p.min_stock)
        self.assertEqual(p.min_stock_efectivo, Decimal("20.00"))

    def test_editar_propaga_a_inventarios_existentes(self):
        self._make("15")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(name="Sede", state="Caracas")
        db.session.add(loc)
        db.session.flush()
        inv = Inventory(
            location_id=loc.id, product_id=p.id,
            current_quantity=Decimal("10.00"), min_stock=Decimal("20.00"),
        )
        db.session.add(inv)
        db.session.commit()

        ProductService.update_product(p.id, {
            "name": p.name,
            "sku": p.sku,
            "product_type_id": None,
            "unit_of_measure": p.unit_of_measure,
            "technical_description": "",
            "waste_limit": "",
            "min_stock": "30",
        })
        db.session.refresh(inv)
        self.assertEqual(inv.min_stock, Decimal("30.00"))

    def test_auto_creacion_de_inventario_usa_el_minimo_del_producto(self):
        self._make("7")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(name="Sede 2", state="Caracas")
        db.session.add(loc)
        db.session.flush()
        inv = _get_or_create_inventory(loc.id, p.id)
        self.assertEqual(inv.min_stock, Decimal("7.00"))

    def _make_supplier_user(self):
        central = Location(id=1, name="Almacén Central", state="Zulia")
        db.session.add(central)
        supplier = Supplier(name="Proveedor Test", tax_id="J-00000000-1")
        db.session.add(supplier)
        role = Role(name="administrator")
        db.session.add(role)
        db.session.flush()
        user = User(
            name="Jefe Test",
            email="jefe@test.com",
            password_hash="x",
            role_id=role.id,
        )
        db.session.add(user)
        db.session.flush()
        return supplier.id, user.id

    def test_compra_crea_inventario_con_minimo_del_producto(self):
        self._make("15")
        p = Product.query.filter_by(sku="HAR-1").one()
        supplier_id, user_id = self._make_supplier_user()
        res = PurchaseService.register_purchase({
            "supplier_id": supplier_id,
            "currency": "USD",
            "exchange_rate": 1,
            "user_id": user_id,
            "invoice_url": "factura-test.pdf",
            "items": [{"product_id": p.id, "quantity": 50, "foreign_price": 2.5}],
        })
        self.assertTrue(res["success"], res)
        inv = Inventory.query.filter_by(product_id=p.id).one()
        self.assertEqual(inv.min_stock, Decimal("15.00"))
        self.assertEqual(inv.current_quantity, Decimal("50.00"))

    def test_compra_sin_minimo_crea_inventario_con_default_20(self):
        self._make("")
        p = Product.query.filter_by(sku="HAR-1").one()
        supplier_id, user_id = self._make_supplier_user()
        res = PurchaseService.register_purchase({
            "supplier_id": supplier_id,
            "currency": "USD",
            "exchange_rate": 1,
            "user_id": user_id,
            "invoice_url": "factura-test.pdf",
            "items": [{"product_id": p.id, "quantity": 30, "foreign_price": 2.5}],
        })
        self.assertTrue(res["success"], res)
        inv = Inventory.query.filter_by(product_id=p.id).one()
        self.assertEqual(inv.min_stock, Decimal("20.00"))
        self.assertEqual(inv.current_quantity, Decimal("30.00"))

    def test_recepcion_traslado_crea_inventario_con_minimo_del_producto(self):
        self._make("7")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(name="Sede Recepción", state="Caracas")
        db.session.add(loc)
        db.session.flush()
        inv = MovementReceptionRepository.get_or_create_inventory(loc.id, p.id)
        self.assertEqual(Decimal(str(inv["min_stock"])), Decimal("7.00"))

    def test_recepcion_traslado_sin_minimo_usa_default_20(self):
        self._make("")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(name="Sede Recepción 2", state="Caracas")
        db.session.add(loc)
        db.session.flush()
        inv = MovementReceptionRepository.get_or_create_inventory(loc.id, p.id)
        self.assertEqual(Decimal(str(inv["min_stock"])), Decimal("20.00"))

    def _new_admin(self):
        role = Role(name="admin")
        db.session.add(role)
        db.session.flush()
        user = User(
            name="Admin Test",
            email="admin@test.com",
            password_hash="x",
            role_id=role.id,
        )
        db.session.add(user)
        db.session.commit()
        return user

    def test_alerta_stock_bajo_usa_minimo_del_producto(self):
        self._make("15")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(id=1, name="Almacén Central", state="Zulia")
        db.session.add(loc)
        db.session.flush()
        inv = Inventory(
            location_id=loc.id, product_id=p.id,
            current_quantity=Decimal("10.00"), min_stock=Decimal("15.00"),
        )
        db.session.add(inv)
        db.session.commit()
        with self.app.test_request_context("/"):
            login_user(self._new_admin())
            alarmas = obtener_alarmas_para_dashboard()
        self.assertTrue(any(a["product_name"] == "Harina"
                            and a["min_stock"] == 15.0
                            and a["new_quantity"] == 10.0
                            for a in alarmas))

    def test_alerta_no_dispara_con_stock_sobre_el_minimo(self):
        self._make("15")
        p = Product.query.filter_by(sku="HAR-1").one()
        loc = Location(id=1, name="Almacén Central", state="Zulia")
        db.session.add(loc)
        db.session.flush()
        inv = Inventory(
            location_id=loc.id, product_id=p.id,
            current_quantity=Decimal("50.00"), min_stock=Decimal("15.00"),
        )
        db.session.add(inv)
        db.session.commit()
        with self.app.test_request_context("/"):
            login_user(self._new_admin())
            alarmas = obtener_alarmas_para_dashboard()
        self.assertFalse(any(a["product_name"] == "Harina" for a in alarmas))

    def test_validator_rechaza_negativo(self):
        is_valid, errors, _ = validate_product_form({
            "name": "Queso",
            "unit_of_measure_select": "KG",
            "sku": "QSO-1",
            "product_type_id": "1",
            "min_stock": "-3",
        })
        self.assertFalse(is_valid)
        self.assertIn("min_stock", errors)

    def test_validator_acepta_vacio(self):
        is_valid, errors, data = validate_product_form({
            "name": "Queso",
            "unit_of_measure_select": "KG",
            "sku": "QSO-2",
            "product_type_id": "1",
            "min_stock": "",
        })
        self.assertTrue(is_valid, errors)
        self.assertIsNone(data["min_stock"])


if __name__ == "__main__":
    unittest.main()