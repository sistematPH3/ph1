# Test integral (Rápido 1 - Módulo 8): flujo REAL de registro -> snapshot.
#
# A diferencia de test_snapshots (que inyecta filas directo), aquí se usa el
# flujo operativo completo para comprobar que las estadísticas aguantan datos
# producidos por los servicios reales:
#   - register_consumption (guardar el audit como JSON *string* era un error que
#     reventaba el cajón: 'str' object has no attribute 'get').
#   - register_waste con el tipo VENCIDO (valoriza unit_cost con el motor de
#     costos, metodo='lote') y con un tipo sensible (queda PENDIENTE).
#   - compras y traslados (pérdidas por missing_quantity).
#
# Uso:
#   .venv/bin/python -m unittest tests.analytics.test_integracion_registro -v

import os
import unittest
from datetime import date, datetime, timedelta, timezone
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
from app.models import (
    Supplier,  # noqa: E402
    AuditLog, Inventory, Location, Movement, MovementDetail, Product, Purchase,
    PurchaseDetail, Role, SnapshotMetric, SnapshotPeriodType, StatisticsSnapshot,
    User, Waste, WasteDetail, WasteType,
)


class RegistroSnapshotsTest(unittest.TestCase):

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
        # El id del rol debe ser estables (is_admin == role_id 1), por eso se
        # fuerza explícitamente (igual que en tests/waste/test_register_waste).
        role = Role(id=1, name="Administrator")
        db.session.add(role)
        db.session.flush()
        self.user = User(name="Admin", email="admin@integ.test",
                         password_hash="x", role_id=role.id)
        db.session.add(self.user)
        db.session.flush()
        # Sede Central id=1 (convención del sistema) y sedes operativas.
        self.central = Location(id=1, name="Central", state="Caracas", is_active=True)
        self.sede = Location(id=2, name="Sede Prueba", state="Caracas", is_active=True)
        self.origen = Location(id=3, name="Bodega Origen", state="Caracas", is_active=True)
        db.session.add_all([self.central, self.sede, self.origen])
        db.session.flush()
        self.product = Product(
            name="Tomate", sku="TOM-INT", unit_of_measure="kg",
            waste_limit=20.0, is_active=True,
        )
        db.session.add(self.product)
        db.session.flush()
        self.inventory = Inventory(
            location_id=self.sede.id, product_id=self.product.id,
            current_quantity=50.0, transit_quantity=0.0,
            reserved_quantity=0.0, min_stock=5.0,
        )
        db.session.add(self.inventory)
        db.session.flush()

        # Proveedor para tests de compras
        self.supplier = Supplier(name="Proveedor Test", tax_id="J-00000000-1")
        db.session.add(self.supplier)
        db.session.flush()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # Escenario base: compra del lote en la Central + traslado a la sede.
    # Nota de tiempos: register_consumption registra su audit con datetime.now()
    # (hora LOCAL), y el motor de costos solo ve compras con purchase_date <= la
    # fecha del hecho. Las compras/traslados se siembran "hace 2 minutos" en
    # hora local para quedar dentro del período actual y anteriores al registro.
    # ------------------------------------------------------------------
    def _compra_lote(self, lote, precio, cantidad=50.0, vence=None):
        p = Purchase(
            purchase_date=datetime.now() - timedelta(minutes=2),
            total_amount=Decimal(str(precio * cantidad)),
            currency="USD",
            exchange_rate=Decimal("36.50"),
            invoice_url="http://x",
            status="COMPLETED",
            user_id=self.user.id,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=p.id,
            product_id=self.product.id,
            lot_number=lote,
            quantity=Decimal(str(cantidad)),
            foreign_price=Decimal(str(precio)),
            price_bs=Decimal(str(precio * 36.50)),
            expiration_date=vence,
        ))
        db.session.flush()
        return p

    def _trasladar_lote(self, lote, cantidad=50.0, status="COMPLETED",
                        missing=Decimal("0.00"), destino=None, vence=None,
                        origin=None):
        m = Movement(
            type="TRASLADO",
            origin_location_id=(origin or self.origen).id,
            destination_location_id=(destino or self.sede).id,
            status=status,
            user_id=self.user.id,
            date=datetime.now() - timedelta(minutes=2),
        )
        db.session.add(m)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=m.id,
            product_id=self.product.id,
            lot_number=lote,
            quantity=Decimal(str(cantidad)),
            received_quantity=Decimal(str(cantidad - float(missing))),
            missing_quantity=missing,
            expiration_date=vence if vence is not None else (date.today() - timedelta(days=5)),
        ))
        db.session.flush()
        return m

    def _misma_consulta_snapshot(self, metric):
        inicio, _ = _periodo_actual()
        return StatisticsSnapshot.query.filter_by(
            location_id=self.sede.id,
            metric=metric,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).first()

    # ==================================================================
    # 1) CONSUMO REAL -> KITCHEN_CONSUMPTION
    # ==================================================================
    def test_consumo_real_con_lote_genera_snapshot(self):
        # Registro el lote disponible (COMPLETADO) y su compra para el costo.
        self._compra_lote("L-1", 10.0)
        self._trasladar_lote("L-1")
        db.session.commit()

        from app.inventory.services.register_consumption_service import register_consumption
        res = register_consumption(
            self.sede.id,
            [{"product_id": self.product.id, "quantity": 5.0, "lot_number": "L-1"}],
            self.user.id,
        )
        self.assertTrue(res["success"])

        # El audit real se guarda como string JSON (json.dumps en el repo).
        log = AuditLog.query.filter_by(action="GASTO_COCINA").one()
        self.assertIsInstance(log.changed_data, str)

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.KITCHEN_CONSUMPTION)
        self.assertIsNotNone(snap)
        # 5 unidades * costo del lote (10 USD) = 50 USD.
        self.assertEqual(snap.quantity, Decimal("5.00"))
        self.assertEqual(snap.amount_usd, Decimal("50.00"))

    def test_consumo_real_fifo_reparte_entre_lotes(self):
        # Dos lotes: L-1 (50 uds) y L-2 (30 uds). Consumo sin lote pedido -> FIFO.
        self._compra_lote("L-1", 10.0)
        self._compra_lote("L-2", 12.0)
        self._trasladar_lote("L-1", cantidad=50.0)
        self._trasladar_lote("L-2", cantidad=30.0)
        db.session.commit()

        from app.inventory.services.register_consumption_service import register_consumption
        res = register_consumption(
            self.sede.id,
            [{"product_id": self.product.id, "quantity": 20.0}],
            self.user.id,
        )
        self.assertTrue(res["success"])

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.KITCHEN_CONSUMPTION)
        self.assertIsNotNone(snap)
        # 20 uds consumidas; la valorización del cajón usa la ÚLTIMA compra
        # (el motor de costos valora por fecha, no por lote en el consumo) -> 12.
        self.assertEqual(snap.quantity, Decimal("20.00"))
        self.assertEqual(snap.amount_usd, Decimal("240.00"))

    # ==================================================================
    # 2) MERMA REAL (VENCIDO) -> WASTE
    # ==================================================================
    def test_merma_vencido_aprobada_valoriza_y_snapshot(self):
        self._compra_lote("L-1", 10.0)
        self._trasladar_lote("L-1")
        tipo = WasteType(name="Vencido", code="VENCIDO", severity="MEDIA",
                         requires_approval=False, applies_central=False,
                         is_active=True)
        db.session.add(tipo)
        db.session.flush()
        db.session.commit()

        from app.waste.services.register_waste_service import register_waste
        res = register_waste(
            user_id=self.user.id,
            location_id=self.sede.id,
            items=[{"product_id": self.product.id, "lot_number": "L-1",
                    "quantity": 5.0, "waste_type_id": tipo.id}],
            evidence_url=None,
            notes="Verificación integral",
        )
        self.assertTrue(res["success"], res.get("message"))
        self.assertEqual(res["status"], "APROBADO")

        # El registro quedó valorizado por el motor de costos (metodo='lote').
        waste = Waste.query.get(res["waste_id"])
        detalle = WasteDetail.query.filter_by(waste_id=waste.id).one()
        self.assertEqual(detalle.unit_cost, Decimal("10.00"))
        self.assertEqual(detalle.subtotal_cost, Decimal("50.00"))
        self.assertEqual(
            float(Inventory.query.get(self.inventory.id).current_quantity), 45.0)

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.WASTE)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.quantity, Decimal("5.00"))
        self.assertEqual(snap.amount_usd, Decimal("50.00"))

    def test_merma_pendiente_quedar_en_la_metrica_documentado(self):
        # Comportamiento ACTUAL (documentado): la métrica WASTE anticipa las
        # mermas PENDIENTE (misma fuente que filas_mermas), aunque el stock
        # físico aún no se descuenta. Lo fijamos para que no cambie por sorpresa.
        tipo = WasteType(name="Ruptura cadena de frio", code="TEMPERATURA",
                         severity="CRITICA", requires_approval=True,
                         applies_central=True, is_active=True)
        db.session.add(tipo)
        db.session.flush()
        self._compra_lote("L-1", 10.0)
        self._trasladar_lote("L-1")
        db.session.commit()

        from app.waste.services.register_waste_service import register_waste
        res = register_waste(
            user_id=self.user.id,
            location_id=self.sede.id,
            items=[{"product_id": self.product.id, "lot_number": "L-1",
                    "quantity": 5.0, "waste_type_id": tipo.id}],
            evidence_url=None,
            notes="Sensible",
        )
        self.assertTrue(res["success"], res.get("message"))
        self.assertEqual(res["status"], "PENDIENTE")

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.WASTE)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.quantity, Decimal("5.00"))
        self.assertEqual(snap.amount_usd, Decimal("50.00"))

    # ==================================================================
    # 3) TRASLADOS -> TRANSFERS (solo pérdidas reales)
    # ==================================================================
    def test_traslado_con_perdida_valora_snapshot(self):
        self._compra_lote("L-1", 10.0)
        # La pérdida sale de la sede (origin) hacia otra sede (destino).
        self._trasladar_lote("L-1", missing=Decimal("2.00"),
                             status="NOVEDAD_FALTANTE",
                             origin=self.sede, destino=self.origen)
        db.session.commit()

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.TRANSFERS)
        self.assertIsNotNone(snap)
        # 2 unidades perdidas valoradas a costo del producto (10 USD).
        self.assertEqual(snap.quantity, Decimal("2.00"))
        self.assertEqual(snap.amount_usd, Decimal("20.00"))

    def test_traslado_en_transito_sin_perdida_no_contamina(self):
        # EN_TRANSITO con missing_quantity=0 -> pérdida 0, no infla la métrica.
        self._compra_lote("L-1", 10.0)
        self._trasladar_lote("L-1", missing=Decimal("0.00"),
                             status="EN_TRANSITO", destino=self.sede)
        db.session.commit()

        from app.analytics.services.snapshots_service import generar_snapshots
        self.assertTrue(generar_snapshots(
            SnapshotPeriodType.MONTHLY, user_id=self.user.id)["success"])
        snap = self._misma_consulta_snapshot(SnapshotMetric.TRANSFERS)
        if snap is not None:
            self.assertEqual(snap.quantity, Decimal("0.00"))
            self.assertEqual(snap.amount_usd, Decimal("0.00"))

    # ==================================================================
    # 4) CUATRO TIPOS DE PERÍODO SIN DUPLICADOS
    # ==================================================================
    def test_cuatro_periodos_generan_sin_duplicar(self):
        self._compra_lote("L-1", 10.0)
        db.session.commit()

        from app.analytics.services.snapshots_service import generar_snapshots
        for period in (SnapshotPeriodType.WEEKLY, SnapshotPeriodType.MONTHLY,
                       SnapshotPeriodType.QUARTERLY, SnapshotPeriodType.ANNUAL):
            r = generar_snapshots(period, user_id=self.user.id)
            self.assertTrue(r["success"], r.get("message"))
            self.assertEqual(r["registros"], 13 * 4, r.get("message"))

        inicio, _ = _periodo_actual()
        # Cada period_type tiene SU PROPIO period_start; verificamos que para
        # el período vigente de cada uno existe exactamente 1 snapshot PURCHASES.
        from app.analytics.services.snapshots_service import calcular_periodo
        for period in (SnapshotPeriodType.WEEKLY, SnapshotPeriodType.MONTHLY,
                       SnapshotPeriodType.QUARTERLY, SnapshotPeriodType.ANNUAL):
            ini, _ = calcular_periodo(period)
            filas = StatisticsSnapshot.query.filter_by(
                metric=SnapshotMetric.PURCHASES,
                period_type=period,
                period_start=ini,
            ).all()
            self.assertEqual(len(filas), 1,
                             f"Debe existir 1 snapshot {period} sin duplicados")
            self.assertTrue(all(f.amount_usd == Decimal("500.00") for f in filas))

    # ==================================================================
    # 5) ROBUSTEZ DEL READER DE CONSUMO (dict o string JSON)
    # ==================================================================
    def test_filas_consumo_tolera_string_y_dict(self):
        from app.analytics.repositories.snapshots_repository import filas_consumo_cocina
        desde = datetime.now(timezone.utc) - timedelta(days=1)
        hasta = datetime.now(timezone.utc) + timedelta(days=1)
        db.session.add(AuditLog(
            affected_table="inventory", action="GASTO_COCINA",
            user_id=self.user.id, location_id=self.sede.id,
            timestamp=datetime.now(timezone.utc),
            changed_data={"product_id": self.product.id, "quantity_changed": -7.0},
        ))
        db.session.add(AuditLog(
            affected_table="inventory", action="GASTO_COCINA",
            user_id=self.user.id, location_id=self.sede.id,
            timestamp=datetime.now(timezone.utc),
            changed_data='{"product_id": ' + str(self.product.id) + ', "quantity_changed": -3.0}',
        ))
        db.session.commit()

        filas = filas_consumo_cocina(desde, hasta)
        cantidad_total = sum(float(f["quantity"]) for f in filas)
        self.assertEqual(cantidad_total, 10.0)
        self.assertEqual(len(filas), 2)

    # ==================================================================
    # 6) REGRESIÓN: BUG 1 - el UPSERT no borraba snapshots sin datos
    # ==================================================================
    def test_cancelar_merma_elimina_snapshot_al_regenerar(self):
        # Antes: una merma contada y luego cancelada seguía en el cajón aunque
        # se regenerara (guardar_snapshots nunca borraba las filas obsoletas).
        self._compra_lote("L-CAN", 10.0)
        self._trasladar_lote("L-CAN")
        db.session.commit()

        from app.analytics.services.snapshots_service import generar_snapshots
        w = Waste(status="PENDIENTE", date=datetime.now(),
                  location_id=self.sede.id, user_id=self.user.id,
                  notes="cancelar",
                  details=[WasteDetail(product_id=self.product.id, quantity=5,
                                       status="PENDIENTE",
                                       unit_cost=Decimal("10"),
                                       lot_number="L-CAN")])
        db.session.add(w)
        db.session.commit()
        generar_snapshots(SnapshotPeriodType.MONTHLY)
        snap = self._misma_consulta_snapshot(SnapshotMetric.WASTE)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("50.00"))

        w.status = "CANCELADA"
        w.cancelled_at = datetime.now()
        db.session.commit()
        generar_snapshots(SnapshotPeriodType.MONTHLY)  # noqa: F401
        self.assertIsNone(self._misma_consulta_snapshot(SnapshotMetric.WASTE))

    # ==================================================================
    # 7) REGRESIÓN: BUG 2 - tras resolver la disputa no queda pérdida fantasma
    # ==================================================================
    def _disputa_novedad(self, missing=Decimal("2.00")):
        """Traslado NOVEDAD_FALTANTE de la sede al origen + auditoría de
        recepción (igual que la deja movement_reception_service)."""
        self._compra_lote("L-TRS", 10.0)
        mov = self._trasladar_lote("L-TRS", missing=missing,
                                   status="NOVEDAD_FALTANTE",
                                   origin=self.sede, destino=self.origen)
        detail = MovementDetail.query.filter_by(movement_id=mov.id).one()
        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_NOVEDAD",
            severity="ALERTA",
            user_id=self.user.id,
            location_id=self.origen.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RECEPCION_NOVEDAD",
                "notes": "Carga registrada en muelle",
                "erroneous_products_delivered": [],
                "discrepancies": [{
                    "product_id": self.product.id,
                    "type": "FALTANTE",
                    "authorized_qty": float(50),
                    "physical_received_qty": float(50 - float(missing)),
                    "extra_units": 0.0,
                    "notes": "Novedad registrada",
                }],
            },
        ))
        db.session.commit()
        return mov, detail

    def test_resolver_acreditar_destino_no_cuenta_perdida_fantasma(self):
        # La resolución (ACEPTAR/Acreditación o Reintegro) NO es pérdida: el
        # detail debe quedar con missing_quantity=0 y el snapshot desaparecer.
        from app.analytics.services.snapshots_service import generar_snapshots
        from app.logistics.services.movement_dispute_service import resolve_dispute
        _, detail = self._disputa_novedad(missing=Decimal("2.00"))

        generar_snapshots(SnapshotPeriodType.MONTHLY)
        snap = self._misma_consulta_snapshot(SnapshotMetric.TRANSFERS)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.amount_usd, Decimal("20.00"))

        resolve_dispute(detail.movement_id, {
            f"item_{detail.id}_action": "ACEPTAR_RECEPCION",
            "general_notes": "Se queda la mercancía",
        }, user_id=self.user.id)
        db.session.refresh(detail)
        self.assertEqual(detail.missing_quantity, Decimal("0.00"))

        generar_snapshots(SnapshotPeriodType.MONTHLY)
        snap = self._misma_consulta_snapshot(SnapshotMetric.TRANSFERS)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.quantity, Decimal("0.00"))
        self.assertEqual(snap.amount_usd, Decimal("0.00"))

    def test_resolver_baja_extraviado_mantiene_perdida_real(self):
        # La baja/extravío SÍ es pérdida: debe seguir contando tras resolver.
        from app.analytics.services.snapshots_service import generar_snapshots
        from app.logistics.services.movement_dispute_service import resolve_dispute
        _, detail = self._disputa_novedad(missing=Decimal("2.00"))

        resolve_dispute(detail.movement_id, {
            f"item_{detail.id}_action": "BAJA_EXTRAVIO_PARCIAL",
            "general_notes": "Extravío confirmado",
        }, user_id=self.user.id)
        db.session.refresh(detail)
        self.assertEqual(detail.missing_quantity, Decimal("2.00"))

        generar_snapshots(SnapshotPeriodType.MONTHLY)
        snap = self._misma_consulta_snapshot(SnapshotMetric.TRANSFERS)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.quantity, Decimal("2.00"))
        self.assertEqual(snap.amount_usd, Decimal("20.00"))

    # ==================================================================
    # 8) REGRESIÓN: moneda de compra restringida a USD/EUR
    # ==================================================================
    def test_registrar_compra_moneda_no_soportada_rechazada(self):
        from app.logistics.services.purchase_service import PurchaseService
        res = PurchaseService.register_purchase({
            "supplier_id": self.supplier.id, "currency": "BS", "exchange_rate": 36.5,
            "user_id": self.user.id, "invoice_url": "", "items": [],
        })
        self.assertFalse(res["success"])
        self.assertIn("USD o EUR", res["message"])

    def test_snapshot_omite_compra_con_moneda_inedita(self):
        # Defensa a nivel de lectura: una compra con moneda fuera de USD/EUR
        # (legacy o mala data) no distorsiona el cajón ni se valora como USD.
        from app.analytics.services.snapshots_service import generar_snapshots
        p = Purchase(
            purchase_date=datetime.now() - timedelta(minutes=2),
            total_amount=Decimal("50.00"), currency="BS",
            exchange_rate=Decimal("36.50"), invoice_url="http://x",
            status="COMPLETED", user_id=self.user.id,
        )
        db.session.add(p)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=p.id, product_id=self.product.id, lot_number="L-BS",
            quantity=Decimal("50"), foreign_price=Decimal("10"),
            price_bs=Decimal("370.00"),
        ))
        db.session.commit()

        generar_snapshots(SnapshotPeriodType.MONTHLY)
        inicio, _ = _periodo_actual()
        filas = StatisticsSnapshot.query.filter_by(
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=inicio,
        ).all()
        self.assertEqual(len(filas), 0)


def _periodo_actual():
    from app.analytics.services.snapshots_service import calcular_periodo
    return calcular_periodo(SnapshotPeriodType.MONTHLY)


if __name__ == "__main__":
    unittest.main()