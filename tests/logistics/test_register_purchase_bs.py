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

from app import create_app, db  # noqa: E402
from app.models import (ExchangeRateHistory, Inventory, Location,  # noqa: E402
                        Product, Purchase, PurchaseDetail, Role, Supplier, User)
from app.logistics.requests.purchase_validators import PurchaseValidator  # noqa: E402
from app.logistics.services.purchase_service import PurchaseService  # noqa: E402


class RegisterPurchaseBsTest(unittest.TestCase):

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

        self.rol = Role(name="Administrator")
        self.central = Location(id=1, name="Almacén Central", state="Caracas",
                                is_active=True)
        self.comprador = User(name="Comprador Test", email="buy@ph.test",
                              password_hash="x", role_id=1)
        db.session.add(self.rol)
        db.session.flush()
        self.comprador.role_id = self.rol.id
        self.proveedor = Supplier(name="Proveedor Bs", tax_id="J-0002")
        self.harina = Product(name="Harina", sku="HAR-BS", unit_of_measure="KG")
        db.session.add_all([self.central, self.comprador, self.proveedor,
                            self.harina])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def datos_registro(self, moneda, tasa, precio, cantidad=100, alias=None, descripcion=''):
        data = {
            'supplier_id': self.proveedor.id,
            'currency': alias or moneda,
            'exchange_rate': str(tasa),
            'user_id': self.comprador.id,
            'invoice_url': descripcion or f"factura-{moneda}.pdf",
            'items': [
                {
                    'product_id': self.harina.id,
                    'quantity': str(cantidad),
                    'foreign_price': str(precio),
                    'expiration_date': '2026-12-31',
                    'lot_number': f"LOTE-{moneda}",
                }
            ]
        }
        return data

    def test_registro_en_bs_guarda_price_bs_sin_multiplicar_por_tasa(self):
        res = PurchaseService.register_purchase(
            self.datos_registro('BS', 820, 50, cantidad=1))

        self.assertTrue(res["success"])
        purchase = db.session.query(Purchase).get(res["purchase_id"])
        detail = db.session.query(PurchaseDetail).filter_by(
            purchase_id=purchase.id).first()

        self.assertEqual(purchase.currency, 'BS')
        self.assertEqual(purchase.total_amount, Decimal('50.00'))
        self.assertEqual(detail.foreign_price, Decimal('50.00'))
        # En Bs el precio ya es bolívares: la tasa NO debe multiplicarse.
        self.assertEqual(detail.price_bs, Decimal('50.00'))
        self.assertEqual(purchase.exchange_rate, Decimal('820'))

    def test_registro_en_usd_mantiene_equivalente_en_bs(self):
        res = PurchaseService.register_purchase(
            self.datos_registro('USD', 800, 40, cantidad=10))

        self.assertTrue(res["success"])
        purchase = db.session.query(Purchase).get(res["purchase_id"])
        detail = db.session.query(PurchaseDetail).filter_by(
            purchase_id=purchase.id).first()

        # 40 es el TOTAL de la línea: por unidad son 4.00
        self.assertEqual(purchase.total_amount, Decimal('40.00'))
        self.assertEqual(detail.foreign_price, Decimal('4.00'))
        self.assertEqual(detail.price_bs, Decimal('3200.00'))

    def test_total_de_linea_se_divide_entre_cantidad(self):
        res = PurchaseService.register_purchase(
            self.datos_registro('USD', 814.6908, 40, cantidad=500))

        self.assertTrue(res["success"])
        purchase = db.session.query(Purchase).get(res["purchase_id"])
        detail = db.session.query(PurchaseDetail).filter_by(
            purchase_id=purchase.id).first()

        self.assertEqual(purchase.total_amount, Decimal('40.00'))
        self.assertEqual(detail.foreign_price, Decimal('0.08'))
        self.assertEqual(detail.price_bs, Decimal('65.18'))
        self.assertEqual(
            detail.quantity * detail.foreign_price, Decimal('40.00'))

    def test_aliases_de_bolivares_se_normalizan_a_bs(self):
        for alias in ('VES', 'BS.', 'BSS'):
            with self.subTest(alias=alias):
                res = PurchaseService.register_purchase(
                    self.datos_registro('BS', 820, 50, alias=alias))
                self.assertTrue(res["success"])
                purchase = db.session.query(Purchase).get(res["purchase_id"])
                self.assertEqual(purchase.currency, 'BS')

    def test_validador_acepta_bs_pero_rechaza_otra_moneda(self):
        bases = {'supplier_id': self.proveedor.id,
                 'exchange_rate': '820',
                 'user_id': self.comprador.id}
        for moneda in ('USD', 'EUR', 'BS', 'VES', 'BS.', 'BSS'):
            with self.subTest(moneda=moneda):
                errors = PurchaseValidator.validate_header(
                    dict(bases, currency=moneda))
                self.assertNotIn('currency', errors)

        errors = PurchaseValidator.validate_header(
            dict(bases, currency='MXN'))
        self.assertIn('currency', errors)

    def test_precio_con_puntos_de_miles_se_registra_correctamente(self):
        res = PurchaseService.register_purchase(
            self.datos_registro('BS', 977.8778, '2.000.000', cantidad=1))

        self.assertTrue(res["success"])
        purchase = db.session.query(Purchase).get(res["purchase_id"])
        detail = db.session.query(PurchaseDetail).filter_by(
            purchase_id=purchase.id).first()

        self.assertEqual(purchase.total_amount, Decimal('2000000.00'))
        self.assertEqual(detail.foreign_price, Decimal('2000000.00'))
        self.assertEqual(detail.price_bs, Decimal('2000000.00'))

    def test_validador_acepta_miles_y_coma_decimal(self):
        items = [{'product_id': self.harina.id, 'quantity': '2.000',
                  'foreign_price': '2.000.000'}]
        self.assertFalse(PurchaseValidator.validate_items(items))

        items_d = [{'product_id': self.harina.id, 'quantity': '2,5',
                    'foreign_price': '2.000,50'}]
        self.assertFalse(PurchaseValidator.validate_items(items_d))

        errores = PurchaseValidator.validate_header(
            {'supplier_id': self.proveedor.id, 'currency': 'BS',
             'exchange_rate': '977,8778', 'user_id': self.comprador.id})
        self.assertNotIn('exchange_rate', errores)


if __name__ == '__main__':
    unittest.main()