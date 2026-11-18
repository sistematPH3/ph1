# =============================================================================
# REGRESIÓN: NOVEDADES OFICIALES DE RECEPCIÓN EN LA AUDITORÍA DE INVENTARIO
# -----------------------------------------------------------------------------
# Qué verifica:
#   Cada una de las 10 novedades oficiales del formulario de recepción se
#   muestra con su etiqueta, título e icono propios; las causas cualitativas
#   (frío, vencimiento, lote, custodia, producto erróneo, mixta) conservan las
#   cantidades limpias (sin falsos faltantes) y el rechazo por espacio reporta
#   la cantidad rechazada en lugar de un faltante del proveedor.
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
from app.waste.services.auditinventory_service import (
    RECEPTION_NOVELTY_LABELS,
    get_inventory_audit_entries,
)
from app.time_utils import current_ve_time


# (novedad general, condición del renglón, despachado, recibido, icono esperado)
NOVEDADES = [
    ("CONFORME", "CONFORME", 10.0, 10.0, None),
    ("FALTANTE_CONTEO", "FALTANTE_CONTEO", 10.0, 6.0, "bi-exclamation-triangle-fill"),
    ("SOBRANTE_EXCEDENTE", "SOBRANTE_EXCEDENTE", 10.0, 12.0, "bi-box-seam-fill"),
    ("PRODUCTO_ERRONEO", "PRODUCTO_ERRONEO", 10.0, 0.0, "bi-exclamation-octagon-fill"),
    ("INCIDENCIA_TEMPERATURA", "INCIDENCIA_TEMPERATURA", 10.0, 10.0, "bi-thermometer-high"),
    ("VENCIMIENTO_PROXIMO", "VENCIMIENTO_PROXIMO", 10.0, 10.0, "bi-calendar-x-fill"),
    ("LOTE_NO_COINCIDE", "LOTE_NO_COINCIDE", 10.0, 10.0, "bi-upc-scan"),
    ("VIOLACION_CUSTODIA", "VIOLACION_CUSTODIA", 10.0, 10.0, "bi-shield-exclamation"),
    ("RECHAZO_POR_ESPACIO", "RECHAZO_POR_ESPACIO", 10.0, 8.0, "bi-x-octagon-fill"),
    ("INCIDENCIA_MIXTA", "INCIDENCIA_MIXTA", 10.0, 8.0, "bi-exclamation-diamond-fill"),
]

CUALITATIVAS = {
    "INCIDENCIA_TEMPERATURA", "VENCIMIENTO_PROXIMO", "LOTE_NO_COINCIDE",
    "VIOLACION_CUSTODIA", "PRODUCTO_ERRONEO", "INCIDENCIA_MIXTA",
}


class AuditInventoryNovedadesTest(unittest.TestCase):

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

    def _reset(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()

    def tearDown(self):
        self._reset()
        self.ctx.pop()

    def _seed(self, novedad, item_cond, dispatched, received):
        # Los tests iteran varias novedades en la misma sesión: se limpia antes
        # de sembrar para no chocar con las claves únicas de usuarios/productos.
        self._reset()
        rol = Role(name="Administrator")
        db.session.add(rol)
        db.session.flush()

        origen = Location(name="Almacén Central", state="Caracas")
        destino = Location(name="Sede Este", state="Caracas")
        db.session.add_all([origen, destino])
        db.session.flush()

        admin = User(
            name="Admin", email="admin.novedades@test.com", password_hash="x",
            role_id=rol.id,
        )
        # Un SKU por novedad: los tests iteran varias novedades en la misma
        # transacción y el SKU es único en la tabla de productos.
        producto = Product(
            name="Huevos", sku=f"HUE-{novedad}", unit_of_measure="kg",
            waste_limit=10, is_active=True,
        )
        db.session.add_all([admin, producto])
        db.session.flush()

        movimiento = Movement(
            type="TRASLADO", origin_location_id=origen.id,
            destination_location_id=destino.id,
            status="COMPLETADO" if novedad == "CONFORME" else novedad,
            user_id=admin.id,
        )
        db.session.add(movimiento)
        db.session.flush()

        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_CONFORME" if novedad == "CONFORME" else "RECEPCION_NOVEDAD",
            severity="NORMAL" if novedad == "CONFORME" else "ALERTA",
            user_id=admin.id,
            location_id=destino.id,
            timestamp=current_ve_time(),
            changed_data={
                "movement_id": movimiento.id,
                "event": "RECEPCION_CONFORME" if novedad == "CONFORME" else "RECEPCION_NOVEDAD",
                "novelty_type": novedad,
                "origin_location_id": origen.id,
                "destination_location_id": destino.id,
                "items": [{
                    "product_id": producto.id,
                    "sku": producto.sku,
                    "product_name": "Huevos",
                    "lot_number": "L-9",
                    "dispatched_qty": dispatched,
                    "received_qty": received,
                    "missing_qty": max(0.0, dispatched - received),
                    "item_condition": item_cond,
                    "specific_novelty": item_cond,
                }],
                "notes": f"Simulación de la novedad {novedad}",
            },
        ))
        db.session.commit()
        return admin

    def _fila_recepcion(self, admin):
        entradas = get_inventory_audit_entries({}, admin, True)
        recepciones = [e for e in entradas if e["event_type"] == "recepcion"]
        self.assertEqual(len(recepciones), 1)
        return recepciones[0]

    def test_cada_novedad_oficial_se_presenta_con_su_etiqueta_y_titulo(self):
        for novedad, item_cond, dispatched, received, icon in NOVEDADES:
            admin = self._seed(novedad, item_cond, dispatched, received)
            fila = self._fila_recepcion(admin)

            self.assertEqual(fila["product"], "Huevos", novedad)
            self.assertEqual(fila["lot"], "L-9", novedad)

            if novedad == "CONFORME":
                self.assertEqual(fila["novelty_kind"], "ninguna")
                self.assertFalse(fila["has_novedad"])
                self.assertIn("conforme", fila["novelty_title"].lower())
            else:
                self.assertTrue(fila["has_novedad"], novedad)
                # Las novedades de cantidad se normalizan a FALTANTE/SOBRANTE;
                # las cualitativas conservan su código oficial.
                if novedad in CUALITATIVAS:
                    self.assertEqual(fila["novelty"], novedad)
                self.assertEqual(
                    fila["novelty_label"], RECEPTION_NOVELTY_LABELS[novedad], novedad
                )
                self.assertEqual(fila["novelty_icon"], icon, novedad)
                self.assertTrue(fila["novelty_title"].strip(), novedad)

    def test_cualitativas_no_generan_falsos_faltantes_ni_mensajes_de_incompleta(self):
        for novedad, item_cond, dispatched, received, _icon in NOVEDADES:
            if novedad not in CUALITATIVAS:
                continue
            admin = self._seed(novedad, item_cond, dispatched, received)
            fila = self._fila_recepcion(admin)

            self.assertEqual(fila["novelty_kind"], "novedad", novedad)
            self.assertEqual(fila["rejected_qty"], 0.0, novedad)
            if dispatched == received:
                self.assertEqual(fila["missing_qty"], 0.0, novedad)
                self.assertEqual(fila["surplus_qty"], 0.0, novedad)
            self.assertNotIn("llegó incompleta", fila["novelty_title"].lower(), novedad)

    def test_rechazo_por_espacio_reporta_cantidad_rechazada(self):
        admin = self._seed("RECHAZO_POR_ESPACIO", "RECHAZO_POR_ESPACIO", 10.0, 8.0)
        fila = self._fila_recepcion(admin)

        self.assertEqual(fila["novelty_kind"], "rechazo")
        self.assertEqual(fila["missing_qty"], 0.0)
        self.assertEqual(fila["rejected_qty"], 2.0)
        self.assertEqual(fila["dispatched_qty"], 10.0)
        self.assertEqual(fila["received_qty"], 8.0)
        self.assertIn("rechazo", fila["novelty_title"].lower())
        self.assertIn("rechazado: 2", fila["novelty_summary"].lower())

    def test_faltante_real_se_conserva_como_faltante(self):
        admin = self._seed("FALTANTE_CONTEO", "FALTANTE_CONTEO", 10.0, 6.0)
        fila = self._fila_recepcion(admin)

        self.assertEqual(fila["novelty_kind"], "faltante")
        self.assertEqual(fila["missing_qty"], 4.0)
        self.assertEqual(fila["rejected_qty"], 0.0)
        self.assertEqual(fila["novelty"], "FALTANTE")


if __name__ == "__main__":
    unittest.main()
