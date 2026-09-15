# Test del motor de costos (Rápido 1 - Módulo 8):
# regla mixta (lote exacto -> última compra -> promedio-3) y conversión de moneda.
#
# Uso:
#   .venv/bin/python -m unittest tests.inventory.test_product_cost -v

import os
import unittest
from datetime import datetime, timedelta
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
from app.models import (  # noqa: E402
    ExchangeRateHistory, Location, Product, Purchase, PurchaseDetail,
    Role, User,
)


def _ahora():
    return datetime.now()


class ProductCostTest(unittest.TestCase):

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
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        self.user = User(name="U", email="u@cost.test", password_hash="x",
                         role_id=role.id)
        db.session.add(self.user)
        db.session.flush()
        self.prod = Product(name="Tomate", sku="TOM-CC", unit_of_measure="kg")
        db.session.add(self.prod)
        db.session.flush()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _tasa(self, currency, rate):
        db.session.add(ExchangeRateHistory(
            currency=currency, rate=Decimal(str(rate)), source="TEST",
            timestamp=_ahora(), user_id=self.user.id,
        ))
        db.session.flush()

    def _compra(self, units, price, currency="USD", lote=None, fecha=None,
                tasa_bs=None, status="COMPLETED"):
        p = Purchase(
            supplier_id=None,
            purchase_date=fecha or _ahora(),
            total_amount=Decimal(str(units * price)),
            currency=currency,
            exchange_rate=Decimal(str(tasa_bs)) if tasa_bs else None,
            invoice_url="http://x",
            status=status,
            user_id=self.user.id,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=p.id,
            product_id=self.prod.id,
            lot_number=lote,
            quantity=Decimal(str(units)),
            foreign_price=Decimal(str(price)),
            price_bs=Decimal(str(price * tasa_bs)) if tasa_bs else None,
        ))
        db.session.flush()
        return p

    # ------------------------------------------------------------------
    # Sin compras
    # ------------------------------------------------------------------
    def test_sin_compras_devuelve_cero(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD"),
            Decimal("0.00"),
        )

    # ------------------------------------------------------------------
    # Última compra (regla por defecto)
    # ------------------------------------------------------------------
    def test_ultima_compra_usd(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(10, Decimal("10.00"), currency="USD")
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD"),
            Decimal("10.00"),
        )

    def test_ultima_compra_ignora_cancelada(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(10, Decimal("10.00"), currency="USD", status="CANCELADA")
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD"),
            Decimal("0.00"),
        )

    def test_compra_legacy_completado_se_valora(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(10, Decimal("10.00"), currency="USD", status="COMPLETADO")
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD"),
            Decimal("10.00"),
        )

    def test_ignora_compras_posteriores_a_la_fecha(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(10, Decimal("10.00"), currency="USD",
                     fecha=_ahora() + timedelta(days=30))
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, fecha=_ahora(), moneda="USD"),
            Decimal("0.00"),
        )

    # ------------------------------------------------------------------
    # Monedas
    # ------------------------------------------------------------------
    def test_compra_eur_convertida_a_usd(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._tasa("USD", Decimal("36.50"))
        self._tasa("EUR", Decimal("40.00"))
        self._compra(10, Decimal("10.00"), currency="EUR")
        # 10 EUR = 10 * 40 Bs = 400 Bs ; 400 / 36.50 = 10.9589 -> 10.96
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD"),
            Decimal("10.96"),
        )

    def test_conversion_a_bs(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._tasa("USD", Decimal("36.50"))
        self._compra(10, Decimal("10.00"), currency="USD", tasa_bs=Decimal("36.50"))
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="BS"),
            Decimal("365.00"),
        )

    # ------------------------------------------------------------------
    # Promedio-3 (suavizador)
    # ------------------------------------------------------------------
    def test_promedio_ponderado_3(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(10, Decimal("10.00"), currency="USD",
                     fecha=_ahora() - timedelta(days=3))
        self._compra(5, Decimal("20.00"), currency="USD",
                     fecha=_ahora() - timedelta(days=2))
        self._compra(5, Decimal("20.00"), currency="USD",
                     fecha=_ahora() - timedelta(days=1))
        # (10*10 + 5*20 + 5*20) / 20 = 300/20 = 15.00
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD", metodo="promedio3"),
            Decimal("15.00"),
        )

    # ------------------------------------------------------------------
    # Lote exacto
    # ------------------------------------------------------------------
    def test_lote_exacto_gana(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(5, Decimal("8.00"), currency="USD", lote="L-1",
                     fecha=_ahora() - timedelta(days=2))
        self._compra(5, Decimal("12.00"), currency="USD", lote="L-2",
                     fecha=_ahora() - timedelta(days=1))
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD", metodo="lote", lote="L-1"),
            Decimal("8.00"),
        )

    def test_lote_no_encontrado_cae_a_ultima(self):
        from app.inventory.services.product_cost_service import obtener_costo_unitario
        self._compra(5, Decimal("12.00"), currency="USD", lote="L-2",
                     fecha=_ahora() - timedelta(days=1))
        self.assertEqual(
            obtener_costo_unitario(self.prod.id, moneda="USD", metodo="lote", lote="L-9"),
            Decimal("12.00"),
        )

    # ------------------------------------------------------------------
    # Valorización por cantidad
    # ------------------------------------------------------------------
    def test_valorizar_cantidad(self):
        from app.inventory.services.product_cost_service import valorizar_cantidad
        self._compra(10, Decimal("10.00"), currency="USD")
        self.assertEqual(
            valorizar_cantidad(self.prod.id, Decimal("3.00"), moneda="USD"),
            Decimal("30.00"),
        )


if __name__ == "__main__":
    unittest.main()