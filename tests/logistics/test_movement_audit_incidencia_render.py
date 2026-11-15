# =============================================================================
# REGRESIÓN: TIMELINE DE TRASLADOS CON INCIDENCIA DE CALIDAD
# -----------------------------------------------------------------------------
# Qué verifica:
#   El timeline de auditoría pinta una tabla legible (producto, lote,
#   cantidades y condición) para RECEPCION_INCIDENCIA_CALIDAD, en vez de
#   volcar el payload JSON crudo dentro de la interfaz.
# =============================================================================

import os
import unittest

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
from app.models import AuditLog, Location, Movement, Product, Role, User
from app.logistics.services.movement_audit_service import MovementAuditService
from app.time_utils import current_ve_time


class MovementAuditIncidenciaRenderTest(unittest.TestCase):

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

        origen = Location(name="Almacén Central", state="Caracas")
        destino = Location(name="Sede Este", state="Caracas")
        db.session.add_all([origen, destino])
        db.session.flush()

        admin = User(
            name="Admin", email="admin.audit@test.com", password_hash="x",
            role_id=rol.id,
        )
        producto = Product(
            name="Tomate", sku="TOM-1", unit_of_measure="kg",
            waste_limit=10, is_active=True,
        )
        db.session.add_all([admin, producto])
        db.session.flush()

        movimiento = Movement(
            type="TRASLADO", origin_location_id=origen.id,
            destination_location_id=destino.id, status="COMPLETADO",
            user_id=admin.id,
        )
        db.session.add(movimiento)
        db.session.flush()

        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_INCIDENCIA_CALIDAD",
            severity="ALERTA",
            user_id=admin.id,
            location_id=destino.id,
            timestamp=current_ve_time(),
            changed_data={
                "movement_id": movimiento.id,
                "event": "RECEPCION_INCIDENCIA_CALIDAD",
                "novelty_type": "CALIDAD",
                "final_status": "COMPLETADO_CON_NOVEDAD",
                "origin_location_id": origen.id,
                "destination_location_id": destino.id,
                "items": [{
                    "product_id": producto.id,
                    "sku": "TOM-1",
                    "product_name": "Tomate",
                    "lot_number": "L-1",
                    "dispatched_qty": 10.0,
                    "received_qty": 6.0,
                    "missing_qty": 4.0,
                    "item_condition": "INCIDENCIA_TEMPERATURA",
                    "specific_novelty": "TEMPERATURA_FUERA_DE_RANGO",
                }],
                "notes": "Cadena de frío interrumpida en ruta.",
            },
        ))
        db.session.commit()
        return admin

    def test_timeline_pinta_tabla_y_no_json_crudo(self):
        admin = self._seed()

        movimientos, _ = MovementAuditService.get_structured_audits({})
        self.assertEqual(len(movimientos), 1)
        evento = movimientos[0]["events"][0]
        self.assertIsInstance(evento.changed_data, dict)

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion["_user_id"] = str(admin.id)
            sesion["_fresh"] = True

        respuesta = cliente.get("/logistics/movements/audit")

        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.data.decode("utf-8")
        self.assertIn("Recepción con Incidencia de Calidad", html)
        self.assertIn("ph-tbl-recepcion", html)
        self.assertIn("Condición", html)
        self.assertIn("Incidencia Temperatura", html)
        # El payload ya no se vuelca como JSON crudo en la interfaz.
        self.assertNotIn("&quot;items&quot;", html)
        self.assertNotIn("\\u0022items\\u0022", html)


if __name__ == "__main__":
    unittest.main()
