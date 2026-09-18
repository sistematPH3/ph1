# Test de alarmas y configuración del cajón (Rápido 1 - Módulo 8).
#
# Uso:
#   .venv/bin/python -m unittest tests.analytics.test_alarmas -v

import os
import unittest
from datetime import datetime, timezone
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
    Location, Movement, Role, StatisticsSnapshot, SnapshotMetric,
    SnapshotPeriodType, User, Waste,
)


class AlarmasTest(unittest.TestCase):

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
        self.user = User(name="Admin", email="admin@alarmas.test",
                         password_hash="x", role_id=role.id)
        db.session.add(self.user)
        db.session.flush()
        self.loc = Location(name="Sede A", state="Caracas", is_active=True)
        db.session.add(self.loc)
        db.session.flush()
        self.loc_b = Location(name="Sede B", state="Caracas", is_active=True)
        db.session.add(self.loc_b)
        db.session.flush()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    @staticmethod
    def _ventana():
        from app.analytics.services.snapshots_service import periodos_historia
        return periodos_historia(SnapshotPeriodType.MONTHLY)

    def _snapshot(self, metric, start, fin, usd, loc=None):
        db.session.add(StatisticsSnapshot(
            location_id=(loc or self.loc).id,
            metric=metric,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=start, period_end=fin,
            amount_usd=usd, amount_bs=Decimal("0.00"),
            amount_eur=Decimal("0.00"), quantity=Decimal("0.00"),
            record_count=0,
        ))
        db.session.flush()

    def test_configuracion_default(self):
        from app.analytics.services.snapshots_service import leer_configuracion
        config = leer_configuracion()
        self.assertEqual(config["ESTADISTICAS_FACTOR"], "2.0")
        self.assertEqual(config["ESTADISTICAS_MINIMO_USD"], "100.00")
        self.assertEqual(config["ESTADISTICAS_MONEDA"], "USD")

    def test_actualizar_configuracion_ok(self):
        from app.analytics.services.snapshots_service import (
            actualizar_configuracion, leer_configuracion,
        )
        errores = actualizar_configuracion({
            "ESTADISTICAS_FACTOR": "3.0",
            "ESTADISTICAS_MINIMO_USD": "50",
            "ESTADISTICAS_MONEDA": "EUR",
        })
        self.assertEqual(errores, {})
        config = leer_configuracion()
        self.assertEqual(config["ESTADISTICAS_FACTOR"], "3.0")
        self.assertEqual(config["ESTADISTICAS_MINIMO_USD"], "50")
        self.assertEqual(config["ESTADISTICAS_MONEDA"], "EUR")

    def test_actualizar_configuracion_moneda_invalida(self):
        from app.analytics.services.snapshots_service import actualizar_configuracion
        errores = actualizar_configuracion({
            "ESTADISTICAS_FACTOR": "2.0",
            "ESTADISTICAS_MINIMO_USD": "100",
            "ESTADISTICAS_MONEDA": "MXN",
        })
        self.assertIn("ESTADISTICAS_MONEDA", errores)
        self.assertEqual(len(errores), 1)
        # La moneda inválida nunca se persiste.
        from app.analytics.services.snapshots_service import leer_configuracion
        self.assertEqual(leer_configuracion()["ESTADISTICAS_MONEDA"], "USD")

    def test_actualizar_configuracion_invalida(self):
        from app.analytics.services.snapshots_service import actualizar_configuracion
        errores = actualizar_configuracion({
            "ESTADISTICAS_FACTOR": "abc",
            "ESTADISTICAS_MINIMO_USD": "-1",
        })
        self.assertIn("ESTADISTICAS_FACTOR", errores)
        self.assertIn("ESTADISTICAS_MINIMO_USD", errores)
        self.assertEqual(len(errores), 2)

    def test_valor_alto_dispara_alarma(self):
        ventana = self._ventana()
        actual = ventana[-1]
        previos = ventana[:-1]
        for p in previos:
            self._snapshot(SnapshotMetric.PURCHASES, p[0], p[1], Decimal("100.00"))
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("300.00"))

        from app.analytics.services.snapshots_service import evaluar_alarmas
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY)
        filtradas = [a for a in alertas
                     if a["metric"] == SnapshotMetric.PURCHASES
                     and a["location_id"] == self.loc.id]
        self.assertEqual(len(filtradas), 1)
        self.assertEqual(filtradas[0]["valor_usd"], Decimal("300.00"))
        self.assertEqual(filtradas[0]["promedio_usd"], Decimal("100.00"))
        self.assertEqual(filtradas[0]["variacion_pct"], Decimal("200.00"))
        self.assertEqual(filtradas[0]["location_name"], "Sede A")

    def test_valor_bajo_no_alarma(self):
        ventana = self._ventana()
        actual = ventana[-1]
        previos = ventana[:-1]
        for p in previos:
            self._snapshot(SnapshotMetric.PURCHASES, p[0], p[1], Decimal("100.00"))
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("50.00"))

        from app.analytics.services.snapshots_service import evaluar_alarmas
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY)
        self.assertFalse([a for a in alertas
                          if a["location_id"] == self.loc.id])

    def test_sin_promedio_previo_no_alarma(self):
        ventana = self._ventana()
        actual = ventana[-1]
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("500.00"))

        from app.analytics.services.snapshots_service import evaluar_alarmas
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY)
        self.assertEqual(alertas, [])

    def test_filtro_por_sedes(self):
        ventana = self._ventana()
        actual = ventana[-1]
        previos = ventana[:-1]
        for p in previos:
            self._snapshot(SnapshotMetric.PURCHASES, p[0], p[1], Decimal("100.00"), loc=self.loc)
            self._snapshot(SnapshotMetric.PURCHASES, p[0], p[1], Decimal("100.00"), loc=self.loc_b)
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("300.00"), loc=self.loc)
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("300.00"), loc=self.loc_b)

        from app.analytics.services.snapshots_service import evaluar_alarmas
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY, location_ids=[self.loc.id])
        self.assertEqual([a["location_id"] for a in alertas], [self.loc.id])

    def test_persistir_no_necesario_campana_intacta(self):
        """Las alarmas se calculan al vuelo (al estilo stock bajo):
        NO se escriben filas en la bandeja (Notification)."""
        ventana = self._ventana()
        actual = ventana[-1]
        for p in ventana[:-1]:
            self._snapshot(SnapshotMetric.PURCHASES, p[0], p[1], Decimal("100.00"))
        self._snapshot(SnapshotMetric.PURCHASES, actual[0], actual[1], Decimal("400.00"))

        from app.analytics.services.snapshots_service import evaluar_alarmas
        alertas = evaluar_alarmas(SnapshotPeriodType.MONTHLY)
        self.assertTrue([a for a in alertas
                         if a["location_id"] == self.loc.id])

        from app.models import Notification
        self.assertEqual(
            Notification.query.filter_by(type="ALERTA_ESTADISTICA").count(), 0)

    def test_obtener_pendientes(self):
        db.session.add(Waste(
            location_id=self.loc.id, status="PENDIENTE", date=datetime.now(timezone.utc),
            total_quantity=Decimal("1"), total_cost=Decimal("1"), currency="USD",
        ))
        movimiento = Movement(
            type="TRASLADO", origin_location_id=self.loc.id,
            destination_location_id=self.loc_b.id, user_id=self.user.id,
            status="EN_TRANSITO",
        )
        db.session.add(movimiento)
        db.session.flush()
        db.session.add(Movement(
            type="TRASLADO", origin_location_id=self.loc.id,
            destination_location_id=self.loc_b.id, user_id=self.user.id,
            status="NOVEDAD_FALTANTE",
        ))
        db.session.flush()
        db.session.add(Movement(
            type="TRASLADO", origin_location_id=self.loc.id,
            destination_location_id=self.loc_b.id, user_id=self.user.id,
            status="FALTANTE_CONTEO",
        ))
        db.session.flush()
        db.session.add(Movement(
            type="TRASLADO", origin_location_id=self.loc.id,
            destination_location_id=self.loc_b.id, user_id=self.user.id,
            status="RESOLUCION_DISPUTA",
        ))
        db.session.flush()
        db.session.add(Movement(
            type="TRASLADO", origin_location_id=self.loc.id,
            destination_location_id=self.loc_b.id, user_id=self.user.id,
            status="RECEPCION_NOVEDAD",
        ))
        db.session.flush()

        from app.analytics.services.snapshots_service import obtener_pendientes
        pendientes = obtener_pendientes()
        self.assertEqual(pendientes["mermas_pendientes"], 1)
        self.assertEqual(pendientes["traslados_en_transito"], 1)
        # Solo cuentan los estados reales de arbitraje (NOVEDAD_FALTANTE y
        # FALTANTE_CONTEO); las acciones de auditoría no cuentan.
        self.assertEqual(pendientes["disputas_pendientes"], 2)


if __name__ == "__main__":
    unittest.main()