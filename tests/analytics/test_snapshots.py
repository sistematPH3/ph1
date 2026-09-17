# Test del cajón de snapshots (Rápido 1 - Módulo 8):
# generación UPSERT idempotente por sede/período para las 4 métricas.
#
# Uso:
#   .venv/bin/python -m unittest tests.analytics.test_snapshots -v

import os
import unittest
from datetime import datetime
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
    AuditLog, ExchangeRateHistory, Location, Movement, MovementDetail, Product,
    Purchase, PurchaseDetail, Role, StatisticsSnapshot,
    SnapshotMetric, SnapshotPeriodType, User, Waste, WasteDetail,
    WasteType,
)


class SnapshotsTest(unittest.TestCase):

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
        self.user = User(name="Admin", email="admin@snap.test",
                         password_hash="x", role_id=role.id)
        db.session.add(self.user)
        db.session.flush()
        self.loc_a = Location(name="Sede A", state="Caracas", is_active=True)
        self.loc_b = Location(name="Sede B", state="Caracas", is_active=True)
        db.session.add_all([self.loc_a, self.loc_b])
        db.session.flush()
        self.product = Product(name="Tomate", sku="TOM-SN", unit_of_measure="kg")
        db.session.add(self.product)
        db.session.flush()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _compra(self, units=10, price=Decimal("10.00"), currency="USD",
                price_bs=Decimal("36.50"), status="COMPLETED"):
        p = Purchase(
            purchase_date=datetime.utcnow(),
            total_amount=Decimal(str(units * price)),
            currency=currency,
            exchange_rate=price_bs,
            invoice_url="http://x",
            user_id=self.user.id,
            status=status,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=p.id,
            product_id=self.product.id,
            lot_number="LOT-1",
            quantity=Decimal(str(units)),
            foreign_price=price,
            price_bs=price_bs,
        ))
        db.session.flush()

    def _merma(self, status, cantidad, unit_cost=Decimal("10.00"), cancelada=False):
        w = Waste(
            location_id=self.loc_a.id,
            date=datetime.utcnow(),
            user_id=self.user.id,
            status=status,
            total_quantity=cantidad,
            total_cost=Decimal(str(cantidad * unit_cost)),
            currency="USD",
        )
        if cancelada:
            w.cancelled_at = datetime.utcnow()
            w.cancel_reason = "prueba"
        db.session.add(w)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=w.id,
            product_id=self.product.id,
            lot_number="LOT-W",
            quantity=cantidad,
            unit_cost=unit_cost,
            subtotal_cost=Decimal(str(cantidad * unit_cost)),
        ))
        db.session.flush()
        return w

    def _consumo(self, quantities=-5, action="GASTO_COCINA"):
        db.session.add(AuditLog(
            affected_table="inventory",
            action=action,
            user_id=self.user.id,
            location_id=self.loc_a.id,
            timestamp=datetime.utcnow(),
            changed_data={"product_id": self.product.id,
                          "quantity_changed": quantities},
        ))
        db.session.flush()

    def _traslado(self, missing=Decimal("2.00"), status="RECIBIDO"):
        m = Movement(
            type="TRASLADO",
            origin_location_id=self.loc_a.id,
            destination_location_id=self.loc_b.id,
            date=datetime.utcnow(),
            user_id=self.user.id,
            status=status,
        )
        db.session.add(m)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=m.id,
            product_id=self.product.id,
            lot_number="LOT-M",
            quantity=Decimal("10.00"),
            received_quantity=Decimal("8.00"),
            missing_quantity=missing,
        ))
        db.session.flush()
        return m

    def _snapshot(self, metric, inicio, fin, usd, loc=None,
                  period_type=SnapshotPeriodType.MONTHLY):
        db.session.add(StatisticsSnapshot(
            location_id=(loc or self.loc_a).id,
            metric=metric,
            period_type=period_type,
            period_start=inicio, period_end=fin,
            amount_usd=usd, amount_bs=Decimal("0.00"),
            amount_eur=Decimal("0.00"), quantity=Decimal("0.00"),
            record_count=0,
        ))
        db.session.flush()

    def _tasa(self, currency, rate):
        db.session.add(ExchangeRateHistory(
            currency=currency, rate=Decimal(str(rate)), source="TEST",
            timestamp=datetime.utcnow(), user_id=self.user.id,
        ))
        db.session.flush()

    # ------------------------------------------------------------------
    def test_periodos_historia_ventana_13(self):
        from app.analytics.services.snapshots_service import periodos_historia
        periodos = periodos_historia(SnapshotPeriodType.MONTHLY)
        self.assertEqual(len(periodos), 13)
        inicio, fin = periodos[-1]
        self.assertEqual(inicio.day, 1)
        self.assertGreaterEqual(fin, inicio)

    def test_genera_snapshots_compras(self):
        self._compra()
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("100.00"))
        self.assertEqual(snap.amount_bs, Decimal("365.00"))
        self.assertEqual(snap.quantity, Decimal("10.00"))
        self.assertEqual(snap.record_count, 1)

    def test_compras_usd_generan_eur(self):
        self._tasa("USD", Decimal("36.50"))
        self._tasa("EUR", Decimal("38.00"))
        self._compra()
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        # 100 USD * 38,00 / 36,50 = 104,11 EUR (antes quedaba 0,00).
        self.assertEqual(snap.amount_usd, Decimal("100.00"))
        self.assertEqual(snap.amount_eur, Decimal("104.11"))

    def test_genera_snapshots_mermas_excluye_canceladas(self):
        self._merma("APROBADO", 5)
        self._merma("APROBADO", 5, cancelada=True)
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.WASTE,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        # Solo la merma APROBADO activa (la cancelada se ignora aunque esté APROBADO).
        self.assertEqual(snap.amount_usd, Decimal("50.00"))
        self.assertEqual(snap.quantity, Decimal("5.00"))

    def test_genera_snapshots_traslados_valora_perdidas(self):
        self._compra()
        self._traslado(missing=Decimal("2.00"))
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.TRANSFERS,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        # 2 unidades perdidas * $10 unitario = $20.00
        self.assertEqual(snap.amount_usd, Decimal("20.00"))
        self.assertEqual(snap.quantity, Decimal("2.00"))

    def test_genera_snapshots_consumo_cocina(self):
        self._compra()
        self._consumo()
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.KITCHEN_CONSUMPTION,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        # 5 unidades * $10 unitario = $50.00
        self.assertEqual(snap.amount_usd, Decimal("50.00"))
        self.assertEqual(snap.quantity, Decimal("5.00"))

    def test_genera_snapshots_compras_excluye_anuladas(self):
        self._compra(status="ANNULLED")
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNone(snap, "Las compras ANNULLED no deben poblar el cajón PUCHASES")

    def test_genera_snapshots_compras_acepta_estado_legacy(self):
        self._compra(status="COMPLETADO")
        from app.analytics.services.snapshots_service import generar_snapshots
        generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("100.00"))

    def test_genera_snapshots_mermas_parcial_solo_lineas_aprobadas(self):
        w = Waste(
            location_id=self.loc_a.id,
            date=datetime.utcnow(),
            user_id=self.user.id,
            status="APROBADO_PARCIAL",
            total_quantity=Decimal("8.00"),
            total_cost=Decimal("80.00"),
            currency="USD",
        )
        db.session.add(w)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=w.id, product_id=self.product.id, lot_number="LOT-W1",
            quantity=Decimal("5.00"), unit_cost=Decimal("10.00"),
            subtotal_cost=Decimal("50.00"), status="APROBADO",
        ))
        db.session.add(WasteDetail(
            waste_id=w.id, product_id=self.product.id, lot_number="LOT-W2",
            quantity=Decimal("3.00"), unit_cost=Decimal("10.00"),
            subtotal_cost=Decimal("30.00"), status="PENDIENTE",
        ))
        db.session.flush()
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.WASTE,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        # Solo la línea APROBADO (5 x $10); la PENDIENTE aún no impacta.
        self.assertEqual(snap.amount_usd, Decimal("50.00"))
        self.assertEqual(snap.quantity, Decimal("5.00"))

    def test_mermas_por_tipo_grupo_y_parcial(self):
        from app.analytics.services.snapshots_service import obtener_mermas_por_tipo

        vencido = WasteType(name="Vencido", code="VENCIDO")
        danado = WasteType(name="Dañado", code="DANADO")
        db.session.add_all([vencido, danado])
        db.session.flush()

        def merma(status, tipo_id, qty, unit_cost, estado_linea="APROBADO"):
            w = Waste(location_id=self.loc_a.id, date=datetime.utcnow(),
                      user_id=self.user.id, status=status,
                      total_quantity=qty,
                      total_cost=Decimal(str(qty * unit_cost)),
                      currency="USD")
            db.session.add(w)
            db.session.flush()
            db.session.add(WasteDetail(
                waste_id=w.id, product_id=self.product.id,
                waste_type_id=tipo_id, lot_number=f"LOT-{status}-{qty}",
                quantity=qty, unit_cost=unit_cost,
                subtotal_cost=Decimal(str(qty * unit_cost)),
                status=estado_linea,
            ))
            db.session.flush()

        merma("APROBADO", vencido.id, Decimal("4.00"), Decimal("10.00"))
        merma("APROBADO", vencido.id, Decimal("6.00"), Decimal("10.00"))
        merma("PENDIENTE", danado.id, Decimal("2.00"), Decimal("5.00"))
        # Parcial: solo suma la línea APROBADO (8 x $2), no la PENDIENTE (3 x $2).
        w = Waste(location_id=self.loc_a.id, date=datetime.utcnow(),
                  user_id=self.user.id, status="APROBADO_PARCIAL",
                  total_quantity=Decimal("11.00"),
                  total_cost=Decimal("22.00"), currency="USD")
        db.session.add(w)
        db.session.flush()
        db.session.add(WasteDetail(waste_id=w.id, product_id=self.product.id,
                                   waste_type_id=vencido.id, lot_number="LOT-P1",
                                   quantity=Decimal("8.00"), unit_cost=Decimal("2.00"),
                                   subtotal_cost=Decimal("16.00"), status="APROBADO"))
        db.session.add(WasteDetail(waste_id=w.id, product_id=self.product.id,
                                   waste_type_id=vencido.id, lot_number="LOT-P2",
                                   quantity=Decimal("3.00"), unit_cost=Decimal("2.00"),
                                   subtotal_cost=Decimal("6.00"), status="PENDIENTE"))
        db.session.flush()

        por_tipo = obtener_mermas_por_tipo(SnapshotPeriodType.MONTHLY)
        tipos = {t["tipo"]: t for t in por_tipo["tipos"]}
        # Vencido: 4+6 a $10 (aprobadas) + 8 a $2 (línea aprobada de la parcial).
        v = tipos["Vencido"]
        self.assertEqual(v["cantidad"], Decimal("18.00"))
        self.assertEqual(v["monto_usd"], Decimal("116.00"))
        d = tipos["Dañado"]
        self.assertEqual(d["cantidad"], Decimal("2.00"))
        self.assertEqual(d["monto_usd"], Decimal("10.00"))
        # Orden descendente por costo.
        self.assertEqual(por_tipo["tipos"][0]["tipo"], "Vencido")

    def test_mermas_por_tipo_ignora_canceladas(self):
        from app.analytics.services.snapshots_service import obtener_mermas_por_tipo

        tipo = WasteType(name="Robo", code="ROBO")
        db.session.add(tipo)
        db.session.flush()
        w = Waste(location_id=self.loc_a.id, date=datetime.utcnow(),
                  user_id=self.user.id, status="APROBADO",
                  total_quantity=Decimal("5.00"),
                  total_cost=Decimal("25.00"), currency="USD",
                  cancelled_at=datetime.utcnow(), cancel_reason="test")
        db.session.add(w)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=w.id, product_id=self.product.id,
            waste_type_id=tipo.id, lot_number="LOT-C",
            quantity=Decimal("5.00"), unit_cost=Decimal("5.00"),
            subtotal_cost=Decimal("25.00"), status="APROBADO",
        ))
        db.session.flush()
        por_tipo = obtener_mermas_por_tipo(SnapshotPeriodType.MONTHLY)
        self.assertEqual(por_tipo["tipos"], [])

    def test_genera_snapshots_consumo_legacy_con_consumo_cocina(self):
        self._compra()
        self._consumo(action="CONSUMO_COCINA")
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.KITCHEN_CONSUMPTION,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("50.00"))
        self.assertEqual(snap.quantity, Decimal("5.00"))

    def test_grafico_evolucion_no_mezcla_period_types(self):
        from datetime import timedelta
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_grafico_evolucion,
        )
        inicio, fin = calcular_periodo(SnapshotPeriodType.MONTHLY)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("100.00"))
        self._snapshot(SnapshotMetric.PURCHASES, inicio, inicio + timedelta(days=6),
                       Decimal("900.00"),
                       period_type=SnapshotPeriodType.WEEKLY)
        grafico = obtener_grafico_evolucion(SnapshotPeriodType.MONTHLY)
        self.assertEqual(
            grafico["metrics"][SnapshotMetric.PURCHASES][-1],
            100.0,
            "El gráfico mensual no debe contaminarse con snapshots WEEKLY.",
        )

    def test_alarmas_no_mezclan_period_types(self):
        from app.analytics.services.snapshots_service import (
            evaluar_alarmas, periodos_historia,
        )
        ventana = periodos_historia(SnapshotPeriodType.MONTHLY, limite=4)
        previos = [p[0] for p in ventana[:-1]]
        actual = ventana[-1][0]
        for p in previos:
            self._snapshot(SnapshotMetric.WASTE, p, p, Decimal("20.00"))
        self._snapshot(SnapshotMetric.WASTE, actual, actual, Decimal("100.00"))
        # Un snapshot WEEKLY con el mismo period_start no debe entrar en el promedio.
        self._snapshot(SnapshotMetric.WASTE, previos[0], previos[0],
                       Decimal("500.00"),
                       period_type=SnapshotPeriodType.WEEKLY)
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["metric"], SnapshotMetric.WASTE)
        self.assertEqual(alertas[0]["promedio_usd"], Decimal("20.00"))

    def test_upsert_idempotente(self):
        self._compra()
        from app.analytics.services.snapshots_service import generar_snapshots
        generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        inicio, _ = _periodo_actual()
        self.assertEqual(
            StatisticsSnapshot.query.filter_by(
                location_id=self.loc_a.id,
                metric=SnapshotMetric.PURCHASES,
                period_type=SnapshotPeriodType.MONTHLY,
                period_start=inicio,
            ).count(),
            1,
        )
        # Regenerar no duplica el snapshot.
        generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertEqual(
            StatisticsSnapshot.query.filter_by(
                location_id=self.loc_a.id,
                metric=SnapshotMetric.PURCHASES,
                period_type=SnapshotPeriodType.MONTHLY,
                period_start=inicio,
            ).count(),
            1,
        )

    def test_grafico_evolucion_series(self):
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_grafico_evolucion,
        )
        inicio, fin = calcular_periodo(SnapshotPeriodType.MONTHLY)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("100.00"))
        self._snapshot(SnapshotMetric.WASTE, inicio, fin, Decimal("50.00"))
        grafico = obtener_grafico_evolucion(SnapshotPeriodType.MONTHLY)
        self.assertEqual(len(grafico["periods"]), 13)
        self.assertEqual(len(grafico["metrics"][SnapshotMetric.PURCHASES]), 13)
        self.assertEqual(grafico["metrics"][SnapshotMetric.PURCHASES][-1], 100.0)
        self.assertEqual(grafico["metrics"][SnapshotMetric.WASTE][-1], 50.0)

    def test_costo_operativo_formula_literal(self):
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_costo_operativo,
        )
        inicio, fin = calcular_periodo(SnapshotPeriodType.MONTHLY)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("1000.00"))
        self._snapshot(SnapshotMetric.KITCHEN_CONSUMPTION, inicio, fin, Decimal("300.00"))
        self._snapshot(SnapshotMetric.WASTE, inicio, fin, Decimal("150.00"))
        self._snapshot(SnapshotMetric.TRANSFERS, inicio, fin, Decimal("50.00"))
        resultado = obtener_costo_operativo(SnapshotPeriodType.MONTHLY)
        self.assertEqual(resultado["compras"], Decimal("1000.00"))
        self.assertEqual(resultado["consumo"], Decimal("300.00"))
        self.assertEqual(resultado["mermas"], Decimal("150.00"))
        self.assertEqual(resultado["perdidas"], Decimal("50.00"))
        self.assertEqual(resultado["total"], Decimal("500.00"))

    def test_costo_operativo_filtra_por_sede(self):
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_costo_operativo,
        )
        inicio, fin = calcular_periodo(SnapshotPeriodType.MONTHLY)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("1000.00"),
                       loc=self.loc_a)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("9999.00"),
                       loc=self.loc_b)
        resultado = obtener_costo_operativo(
            SnapshotPeriodType.MONTHLY, location_ids=[self.loc_a.id])
        self.assertEqual(resultado["compras"], Decimal("1000.00"))

    def test_comparativo_contra_periodo_anterior(self):
        from app.analytics.services.snapshots_service import (
            obtener_comparativo, periodos_historia,
        )
        anterior, actual = periodos_historia(SnapshotPeriodType.MONTHLY, limite=2)
        self._snapshot(SnapshotMetric.PURCHASES, anterior[0], anterior[1],
                       Decimal("100.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1],
                       Decimal("300.00"), loc=self.loc_a)
        comp = obtener_comparativo(SnapshotPeriodType.MONTHLY, location_ids=[self.loc_a.id])
        m = comp["metricas"][SnapshotMetric.PURCHASES]
        self.assertEqual(m["actual"], Decimal("300.00"))
        self.assertEqual(m["anterior"], Decimal("100.00"))
        self.assertEqual(m["diff"], Decimal("200.00"))
        self.assertEqual(m["variacion_pct"], Decimal("200.00"))

    def test_comparativo_filtra_por_sede(self):
        from app.analytics.services.snapshots_service import (
            obtener_comparativo, periodos_historia,
        )
        anterior, actual = periodos_historia(SnapshotPeriodType.MONTHLY, limite=2)
        self._snapshot(SnapshotMetric.WASTE, anterior[0], anterior[1],
                       Decimal("10.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.WASTE, actual[0], actual[1],
                       Decimal("20.00"), loc=self.loc_b)
        comp = obtener_comparativo(
            SnapshotPeriodType.MONTHLY, location_ids=[self.loc_a.id])
        m = comp["metricas"][SnapshotMetric.WASTE]
        # Sede B no entra: para A el valor actual es 0 pese a que B gastó 20.
        self.assertEqual(m["actual"], Decimal("0.00"))

    def test_ranking_sedes_orden_y_costo_operativo(self):
        from datetime import timedelta
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_ranking_sedes,
        )
        inicio = calcular_periodo(SnapshotPeriodType.MONTHLY)[0]
        fin = inicio + timedelta(days=27)
        for metric, usd_a, usd_b in [
            (SnapshotMetric.PURCHASES, Decimal("1000.00"), Decimal("500.00")),
            (SnapshotMetric.KITCHEN_CONSUMPTION, Decimal("300.00"), Decimal("50.00")),
            (SnapshotMetric.WASTE, Decimal("150.00"), Decimal("10.00")),
            (SnapshotMetric.TRANSFERS, Decimal("50.00"), Decimal("40.00")),
        ]:
            self._snapshot(metric, inicio, fin, usd_a, loc=self.loc_a)
            self._snapshot(metric, inicio, fin, usd_b, loc=self.loc_b)
        ranking = obtener_ranking_sedes(SnapshotPeriodType.MONTHLY)
        self.assertEqual(len(ranking["sedes"]), 2)
        self.assertEqual(ranking["sedes"][0]["location_name"], "Sede A")
        self.assertEqual(ranking["sedes"][0]["mermas_qty"], Decimal("0.00"))
        # Costo operativo = compras - consumo - mermas - pérdidas.
        self.assertEqual(ranking["sedes"][0]["costo_operativo"], Decimal("500.00"))
        self.assertEqual(ranking["sedes"][1]["costo_operativo"], Decimal("400.00"))

    def test_genera_alarmas_medios_son_null_comparativo_ok(self):
        from app.analytics.services.snapshots_service import (
            obtener_comparativo, periodos_historia,
        )
        anterior, _ = periodos_historia(SnapshotPeriodType.MONTHLY, limite=2)
        self._snapshot(SnapshotMetric.PURCHASES, anterior[0], anterior[1],
                       Decimal("100.00"), loc=self.loc_a)
        comp = obtener_comparativo(SnapshotPeriodType.MONTHLY, location_ids=[self.loc_a.id])
        m = comp["metricas"][SnapshotMetric.PURCHASES]
        self.assertEqual(m["actual"], Decimal("0.00"))
        self.assertEqual(m["diff"], Decimal("-100.00"))

    def test_ultimo_periodo_filtra_moneda_y_sede(self):
        from app.analytics.services.snapshots_service import (
            calcular_periodo, obtener_ultimo_periodo,
        )
        inicio, fin = calcular_periodo(SnapshotPeriodType.MONTHLY)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("100.00"),
                       loc=self.loc_a)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, Decimal("200.00"),
                       loc=self.loc_b)
        solo_a = obtener_ultimo_periodo(
            SnapshotPeriodType.MONTHLY, location_ids=[self.loc_a.id])
        self.assertEqual(solo_a[SnapshotMetric.PURCHASES]["monto"], Decimal("100.00"))
        fecha = inicio.replace(year=inicio.year - 1)
        self._snapshot(SnapshotMetric.PURCHASES, fecha, fin, Decimal("7.00"),
                       loc=self.loc_a)
        otro_mes = obtener_ultimo_periodo(
            SnapshotPeriodType.MONTHLY, moneda='USD', location_ids=[self.loc_a.id])
        self.assertEqual(otro_mes[SnapshotMetric.PURCHASES]["monto"], Decimal("100.00"))

    def test_plantillas_render_smoke(self):
        from decimal import Decimal as D
        from flask import render_template
        from flask_login import login_user

        from app.analytics.services.snapshots_service import (
            PERIOD_TYPES, calcular_periodo, leer_configuracion,
            obtener_comparativo, obtener_costo_operativo,
            obtener_grafico_evolucion, obtener_mermas_por_tipo,
            obtener_ranking_sedes, obtener_ultimo_periodo,
        )
        inicio = calcular_periodo(SnapshotPeriodType.MONTHLY)[0]
        from datetime import timedelta
        fin = inicio + timedelta(days=27)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, D("1000.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.PURCHASES, inicio, fin, D("500.00"), loc=self.loc_b)
        self._snapshot(SnapshotMetric.KITCHEN_CONSUMPTION, inicio, fin, D("300.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.KITCHEN_CONSUMPTION, inicio, fin, D("50.00"), loc=self.loc_b)
        self._snapshot(SnapshotMetric.WASTE, inicio, fin, D("150.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.WASTE, inicio, fin, D("10.00"), loc=self.loc_b)
        self._snapshot(SnapshotMetric.TRANSFERS, inicio, fin, D("50.00"), loc=self.loc_a)
        self._snapshot(SnapshotMetric.TRANSFERS, inicio, fin, D("40.00"), loc=self.loc_b)

        sedes = [self.loc_a, self.loc_b]
        with self.app.test_request_context('/', method='GET'):
            login_user(self.user)
            configs = leer_configuracion()
            base = {
                'alertas': [], 'alertas_estadisticas': [],
                'period_type': SnapshotPeriodType.MONTHLY,
                'moneda': configs.get('ESTADISTICAS_MONEDA', 'USD'),
                'configs': configs,
                'sedes': sedes,
                'sede_seleccionada': None,
                'period_types': PERIOD_TYPES,
                'grafico': obtener_grafico_evolucion(SnapshotPeriodType.MONTHLY),
                'ultimo': obtener_ultimo_periodo(SnapshotPeriodType.MONTHLY),
                'costo_operativo': obtener_costo_operativo(SnapshotPeriodType.MONTHLY),
                'comparativo': obtener_comparativo(SnapshotPeriodType.MONTHLY),
                'ranking': obtener_ranking_sedes(SnapshotPeriodType.MONTHLY),
            }
            # La pantalla statistics.html ya no es nuestra (la rehace Mariuska con
            # sus gráficos y filtros). Lo que queda vivo en nuestro cajón es la
            # configuración; verificamos que NINGÚN template repunte hoy a la
            # ruta eliminada (si alguien lo hiciera → BuildError → 500).
            import glob, re
            refs_colgadas = []
            for tpl in glob.glob('app/templates/**/*.html', recursive=True):
                texto = open(tpl, encoding='utf-8').read()
                if re.search(r"url_for\(\s*['\"]analytics\.estadisticas['\"]\s*\)", texto):
                    refs_colgadas.append(tpl)
            self.assertEqual(refs_colgadas, [],
                             f'Referencias a analytics.estadisticas (ya borrado): {refs_colgadas}')
            html_config = render_template('analytics/statistics_config.html',
                                          configs=configs,
                                          period_types=PERIOD_TYPES,
                                          moneda=base.get('moneda', 'USD'),
                                          sedes=sedes,
                                          sede_seleccionada=base.get('sede_seleccionada'))
            self.assertIn('Moneda por defecto', html_config)

            admin = {
                'datos_grafico': base['grafico'],
                'costo_operativo': base['costo_operativo'],
                'comparativo': base['comparativo'],
                'mermas_por_tipo': obtener_mermas_por_tipo(SnapshotPeriodType.MONTHLY),
                'period_type': SnapshotPeriodType.MONTHLY,
                'moneda': base['moneda'],
                'pendientes': {'mermas_pendientes': 0, 'traslados_en_transito': 0,
                               'disputas_pendientes': 0},
            }
            admin.update({k: v for k, v in base.items()
                          if k in ('alarmas', 'alertas_estadisticas')})
            html_admin = render_template('dashboard/admin_dashboard.html', **admin)
            self.assertIn('Mermas por tipo', html_admin)
            # Orden solicitado por el equipo: las estadísticas entran primero
            # (Evolución + Mermas por tipo) y el listado "Atención requerida"
            # queda al final.
            self.assertLess(html_admin.index('Mermas por tipo'),
                            html_admin.index('Atención requerida'))

            html_cfg = render_template('analytics/statistics_config.html',
                                       configs=configs)
            self.assertIn('Moneda por defecto', html_cfg)

            # La pantalla statistics.html ya no es nuestra (la rehace Mariuska
            # con sus gráficos). Verificamos que TAMPOCO ningún template siga
            # renderizándola: si alguien la reintroduce → TemplateNotFound → 500.
            import glob, re
            plantillas_muertas = []
            for tpl in glob.glob('app/templates/**/*.html', recursive=True):
                texto = open(tpl, encoding='utf-8').read()
                if re.search(r"render_template\(\s*['\"]analytics/statistics\.html['\"]\s*\)",
                             texto):
                    plantillas_muertas.append(tpl)
            self.assertEqual(plantillas_muertas, [],
                             f'Templates renderizando la pantalla borrada statistics.html: '
                             f'{plantillas_muertas}')

            # Estado vacío de 'Mermas por tipo': visible pese al display:none de .dash-empty.
            empty_admin = dict(admin)
            empty_admin['mermas_por_tipo'] = {'tipos': [], 'period_label': 'período'}
            html_mermas_vacio = render_template(
                'dashboard/admin_dashboard.html', **empty_admin)
            self.assertIn('Sin mermas valorizadas en el período.', html_mermas_vacio)
            self.assertIn('style="display:block;"', html_mermas_vacio)

    def test_moneda_default_del_config_abre_reporte(self):
        """La moneda guardada en configuración es la que abre las estadísticas."""
        from app.analytics.services.snapshots_service import (
            actualizar_configuracion, leer_configuracion,
        )
        actualizar_configuracion({
            'ESTADISTICAS_FACTOR': '2.0', 'ESTADISTICAS_MINIMO_USD': '100',
            'ESTADISTICAS_MONEDA': 'EUR',
        })
        self.assertEqual(leer_configuracion()['ESTADISTICAS_MONEDA'], 'EUR')

    # ------------------------------------------------------------------
    # Auditoría: exclusiones de traslados y reloj de períodos (VE)
    # ------------------------------------------------------------------

    def test_traslados_cancelado_emisor_no_es_perdida(self):
        """Un TRASLADO CANCELADO_EMISOR (nunca salió) no entra al snapshot.

        Antes del fix contaba con $0 pero inflaba record_count; con el fix
        directamente no genera fila de TRANSFERS.
        """
        self._compra()
        self._traslado(missing=Decimal("0.00"), status="CANCELADO_EMISOR")
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.TRANSFERS,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNone(snap, "Un traslado cancelado por el emisor no debe crear snapshot")

    def test_traslados_anulado_y_rechazado_excluidos(self):
        self._compra()
        self._traslado(missing=Decimal("0.00"), status="ANULADO")
        self._traslado(missing=Decimal("0.00"), status="RECHAZADO")
        from app.analytics.services.snapshots_service import generar_snapshots
        resultado = generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.TRANSFERS,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNone(snap)

    def test_traslados_completado_sin_perdida_registra_cero(self):
        """Recibido conforme (missing=0) genera registro de $0, no del envío."""
        self._compra()
        self._traslado(missing=Decimal("0.00"), status="COMPLETADO")
        from app.analytics.services.snapshots_service import generar_snapshots
        generar_snapshots(SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        inicio, _ = _periodo_actual()
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.TRANSFERS,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("0.00"))
        self.assertEqual(snap.quantity, Decimal("0.00"))

    def test_calcular_periodo_por_defecto_usa_reloj_ve(self):
        """Los límites de período siguen la fecha de Venezuela (UTC-4).

        A las 23:30 VE del último día del mes, UTC ya es el 1º del mes
        siguiente; el período debe seguir siendo el de septiembre.
        """
        from datetime import date
        from unittest.mock import patch

        from app.analytics.services import snapshots_service
        fixed = datetime(2026, 9, 30, 23, 30, 0)
        with patch.object(snapshots_service, 'current_ve_time', return_value=fixed):
            inicio, fin = snapshots_service.calcular_periodo(SnapshotPeriodType.MONTHLY)
        self.assertEqual(inicio, date(2026, 9, 1))
        self.assertEqual(fin, date(2026, 9, 30))

    def test_compra_al_borde_del_mes_queda_en_su_mes_ve(self):
        """Flujo integro: compra de las 23:30 VE del fin de mes se contabiliza
        en septiembre (no en octubre, que es lo que diría el reloj UTC)."""
        from unittest.mock import patch

        from app.analytics.services import snapshots_service
        fixed = datetime(2026, 9, 30, 23, 30, 0)
        self._compra(units=10, price=Decimal("10.00"), currency="USD",
                     price_bs=Decimal("36.50"))
        purchase = Purchase.query.one()
        purchase.purchase_date = fixed
        db.session.flush()
        with patch.object(snapshots_service, 'current_ve_time', return_value=fixed):
            resultado = snapshots_service.generar_snapshots(
                SnapshotPeriodType.MONTHLY, user_id=self.user.id)
        self.assertTrue(resultado["success"])
        snap = StatisticsSnapshot.query.filter_by(
            location_id=self.loc_a.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=fixed.replace(day=1).date(),
        ).first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("100.00"))

    def test_register_purchase_guarda_fecha_reloj_ve(self):
        """register_purchase escribe purchase_date con el reloj VE (no UTC)."""
        from datetime import datetime as _dt
        from unittest.mock import patch

        from app.logistics.services.purchase_service import PurchaseService
        from app.models.inventory_model import Inventory as Inv

        supplier = _make_supplier_here()
        # purchase_service registra en la sede central (id=1) y su auditoría lo
        # exige como FK; la siembra del test la crea explícitamente, evitando
        # chocar con la sede que el propio setUp ya dejó con id=1.
        if Location.query.get(1) is None:
            db.session.add(Location(name="Almacén Central", state="Zulia",
                                    is_active=True, id=1))
            db.session.flush()
        fixed = _dt(2026, 9, 30, 23, 30, 0)
        with patch('app.logistics.services.purchase_service.current_ve_time',
                   return_value=fixed):
            res = PurchaseService.register_purchase({
                "supplier_id": supplier.id,
                "currency": "USD",
                "exchange_rate": "1",
                "user_id": self.user.id,
                "invoice_url": "factura.pdf",
                "items": [{"product_id": self.product.id, "quantity": 5,
                           "foreign_price": "2.00"}],
            })
        self.assertTrue(res["success"], res)
        p = Purchase.query.get(res["purchase_id"])
        self.assertEqual(p.purchase_date, fixed)
        inv = Inv.query.filter_by(location_id=1,
                                  product_id=self.product.id).first()
        self.assertEqual(inv.current_quantity, Decimal("5.00"))


def _make_supplier_here():
    from app.models import Supplier
    sup = Supplier(name="Proveedor Prueba", tax_id="J-00000000-2")
    db.session.add(sup)
    db.session.flush()
    return sup


def _periodo_actual():
    from app.analytics.services.snapshots_service import calcular_periodo
    return calcular_periodo(SnapshotPeriodType.MONTHLY)


if __name__ == "__main__":
    unittest.main()