# =============================================================================
# PRUEBA AUTOMÁTICA DE LA CONFIGURACIÓN DE MERMAS (Parte 4)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) GET  /waste/merma/config      -> solo Admin (no-admin redirige).
#   2) GET  -> muestra los 2 valores actuales (tolerancia y período base).
#   3) POST /api/waste/merma/config  -> Admin guarda y PERSISTE en app_parameters.
#   4) POST con tolerancia < 1.00 o días fuera de 1..90 -> 400 con errores.
#   5) POST como no-admin -> 403 (bloqueado).
#   6) El clasificador (registro + bandeja) LEE los valores configurados
#      (ese es el propósito real de la parte 4 en el sistema).
#
# Uso:
#   .venv/bin/python -m unittest tests.waste.test_merma_config -v
# =============================================================================

import os
import unittest
import json

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
from app.models import Role, User, AppParameter  # noqa: E402
from app.waste.repositories.register_waste_repository import RegisterWasteRepository  # noqa: E402
from app.waste.services.waste_approvals_service import _param_float  # noqa: E402
from app.waste.services.waste_config_service import WasteConfigService  # noqa: E402


class WasteConfigTest(unittest.TestCase):

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
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)

    def _seed(self):
        """Admin, un no-admin (Operations) y los 2 parámetros por defecto."""
        role_admin = Role(name="Administrator")
        role_ops = Role(name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        admin = User(name="Admin", email="admin@config.test",
                     password_hash="x", role_id=role_admin.id)
        ops = User(name="Operador", email="ops@config.test",
                   password_hash="x", role_id=role_ops.id)
        db.session.add_all([admin, ops])
        db.session.flush()

        db.session.add_all([
            AppParameter(key="WASTE_TIME_TOLERANCE", value="1.5",
                         description="Factor de margen de la regla de tiempo"),
            AppParameter(key="WASTE_BASE_PERIOD_DAYS", value="7",
                         description="Periodo base si no hay merma previa"),
        ])
        db.session.commit()
        return {"admin": admin, "ops": ops}

    # ------------------------------------------------------------------
    # CASO 1: SOLO ADMIN puede ver la pantalla
    # ------------------------------------------------------------------
    def test_get_no_admin_redirige(self):
        env = self._seed()
        self._login(env["ops"].id)
        resp = self.client.get("/waste/merma/config")
        self.assertEqual(resp.status_code, 302)

    def test_get_admin_muestra_valores(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.get("/waste/merma/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("1.50", body)
        self.assertIn('value="7"', body)

    # ------------------------------------------------------------------
    # CASO 2: POST válido guarda y persiste en la BD
    # ------------------------------------------------------------------
    def test_post_admin_guarda_y_persiste(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/config",
            data=json.dumps({
                "WASTE_TIME_TOLERANCE": "2.00",
                "WASTE_BASE_PERIOD_DAYS": "14",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        tol = AppParameter.query.filter_by(key="WASTE_TIME_TOLERANCE").first().value
        days = AppParameter.query.filter_by(key="WASTE_BASE_PERIOD_DAYS").first().value
        self.assertEqual(float(tol), 2.00)
        self.assertEqual(int(days), 14)

        # El servicio de lectura refleja lo guardado (lo que usará la UI)
        data = WasteConfigService.get_config_data()
        self.assertEqual(float(data["WASTE_TIME_TOLERANCE"]), 2.00)
        self.assertEqual(int(data["WASTE_BASE_PERIOD_DAYS"]), 14)

    # ------------------------------------------------------------------
    # CASO 3: POST inválido -> 400 con errores
    # ------------------------------------------------------------------
    def test_post_tolerancia_menor_a_1_rechazada(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/config",
            data=json.dumps({"WASTE_TIME_TOLERANCE": "0.50",
                             "WASTE_BASE_PERIOD_DAYS": "10"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("success", True))
        self.assertIn("WASTE_TIME_TOLERANCE", data.get("errors", {}))

    def test_post_dias_fuera_de_rango_rechazados(self):
        env = self._seed()
        self._login(env["admin"].id)
        for bad_days in ("0", "91", "abc"):
            resp = self.client.post(
                "/api/waste/merma/config",
                data=json.dumps({"WASTE_TIME_TOLERANCE": "1.50",
                                 "WASTE_BASE_PERIOD_DAYS": bad_days}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400,
                             f"días '{bad_days}' debió rechazarse")
            self.assertIn("WASTE_BASE_PERIOD_DAYS",
                          resp.get_json().get("errors", {}))

    # ------------------------------------------------------------------
    # CASO 4: no-admin NO puede guardar
    # ------------------------------------------------------------------
    def test_post_no_admin_bloqueado(self):
        env = self._seed()
        self._login(env["ops"].id)
        resp = self.client.post(
            "/api/waste/merma/config",
            data=json.dumps({"WASTE_TIME_TOLERANCE": "1.50",
                             "WASTE_BASE_PERIOD_DAYS": "10"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 302)

        # Y nada cambió en la BD
        tol = AppParameter.query.filter_by(key="WASTE_TIME_TOLERANCE").first()
        self.assertIsNotNone(tol)
        self.assertEqual(float(tol.value), 1.5)

    # ------------------------------------------------------------------
    # CASO 5: el CLASIFICADOR usa los valores configurados
    #   (este es el propósito de la parte 4 en el sistema: el motor de
    #    clasificación de mermas lee la pizarra al momento de decidir)
    # ------------------------------------------------------------------
    def test_clasificador_usa_valores_configurados(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/config",
            data=json.dumps({"WASTE_TIME_TOLERANCE": "2.5",
                             "WASTE_BASE_PERIOD_DAYS": "20"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        # Motor de REGISTRO (Parte 1)
        self.assertEqual(
            RegisterWasteRepository.get_parameter("WASTE_TIME_TOLERANCE", 1.5), 2.5)
        self.assertEqual(
            RegisterWasteRepository.get_parameter("WASTE_BASE_PERIOD_DAYS", 7), 20.0)

        # Motor de la BANDEJA (Parte 3): reconstrucción del motivo por tiempo
        self.assertEqual(_param_float("WASTE_TIME_TOLERANCE", 1.5), 2.5)
        self.assertEqual(_param_float("WASTE_BASE_PERIOD_DAYS", 7), 20.0)


if __name__ == "__main__":
    unittest.main()