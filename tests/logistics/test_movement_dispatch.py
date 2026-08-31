# =============================================================================
# PRUEBA AUTOMÁTICA DEL SERVICIO DE DESPACHO (módulo de Diego)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Emisión de un despacho manual con lote válido asienta salida correcta.
#   2) Un lote inexistente / sin disponibilidad es rechazado por el backend.
#   3) Exceder el saldo neto de un lote es rechazado aunque el stock global alcance.
#   4) Dos renglones sobre el mismo lote no pueden exceder juntos su saldo neto.
#   5) Registros de consumo/auditoría sin product_id ya no contaminan la
#      disponibilidad de los lotes del producto.
#   6) changed_data malformado no tumba la consulta de lotes (sin 500).
#   7) La cancelación rechaza movimientos que no sean DESPACHO.
#   8) Un despacho sin lote es rechazado.
#
# Uso (en la carpeta ph1, Linux/Ubuntu):
#   .venv/bin/python -m unittest tests.logistics.test_movement_dispatch -v
# =============================================================================

import os
import unittest
from datetime import date, datetime

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
from app.models import AuditLog, Inventory, Location, Movement, MovementDetail, Product, Purchase, PurchaseDetail, Role, Supplier, User
from app.logistics.repositories.movement_dispatch_repository import MovementDispatchRepository
from app.logistics.services.movement_dispatch_service import MovementDispatchService


class MovementDispatchTest(unittest.TestCase):

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

    def _seed(self, lot_qty_100=50.0, lot_qty_101=100.0):
        """Lotes del producto entrados por TRASLADO COMPLETADO hacia una sede origen no central."""
        loc_origin = Location(name="Sede Origen", state="Caracas")
        loc_origin.id = 555  # fuerzo la rama no-central (id != 1) por determinismo
        loc_away = Location(name="Sede A", state="Caracas")
        loc_dest = Location(name="Sede Destino", state="Caracas")
        product = Product(name="Tomate", sku="TOM-DSP", unit_of_measure="kg")
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Emisor", email="emisor@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add_all([loc_origin, loc_away, loc_dest, product, user])
        db.session.flush()

        inv = Inventory(
            location_id=loc_origin.id, product_id=product.id,
            current_quantity=lot_qty_100 + lot_qty_101,
            transit_quantity=0.0, min_stock=20
        )
        db.session.add(inv)
        db.session.flush()

        m1 = Movement(
            type="TRASLADO",
            origin_location_id=loc_away.id,
            destination_location_id=loc_origin.id,
            status="COMPLETADO",
            user_id=user.id
        )
        m2 = Movement(
            type="TRASLADO",
            origin_location_id=loc_away.id,
            destination_location_id=loc_origin.id,
            status="COMPLETADO",
            user_id=user.id
        )
        db.session.add_all([m1, m2])
        db.session.flush()

        d1 = MovementDetail(
            movement_id=m1.id, product_id=product.id, lot_number="L-100",
            quantity=lot_qty_100, received_quantity=lot_qty_100,
            missing_quantity=0.00, expiration_date=date(2026, 1, 15)
        )
        d2 = MovementDetail(
            movement_id=m2.id, product_id=product.id, lot_number="L-101",
            quantity=lot_qty_101, received_quantity=lot_qty_101,
            missing_quantity=0.00, expiration_date=date(2026, 6, 1)
        )
        db.session.add_all([d1, d2])
        db.session.commit()

        return {
            "origin": loc_origin, "dest": loc_dest, "product": product,
            "inventory": inv, "user": user, "user_id": user.id,
        }

    def _seed_central(self, lot_qty_100=50.0, lot_qty_101=100.0):
        """Central (id=1): entradas por COMPRAS completadas, como en producción."""
        central = Location(name="Central", state="Caracas")
        central.id = 1
        loc_dest = Location(name="Sede Destino", state="Caracas")
        loc_dest.id = 557  # PK explícito para no colisionar con la secuencia
        product = Product(name="Tomate", sku="TOM-DSPC", unit_of_measure="kg")
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Emisor", email="emisor@test.com",
                    password_hash="x", role_id=role.id)
        supplier = Supplier(name="Proveedor", tax_id="J-00000000-1",
                            phone="0000", email="prov@test.com")
        db.session.add_all([central, loc_dest, product, user, supplier])
        db.session.flush()

        inv = Inventory(
            location_id=central.id, product_id=product.id,
            current_quantity=lot_qty_100 + lot_qty_101,
            transit_quantity=0.0, min_stock=20
        )
        db.session.add(inv)
        db.session.flush()

        p1 = Purchase(supplier_id=supplier.id, status="COMPLETED", invoice_url="inv1.pdf")
        p2 = Purchase(supplier_id=supplier.id, status="COMPLETED", invoice_url="inv2.pdf")
        db.session.add_all([p1, p2])
        db.session.flush()
        db.session.add_all([
            PurchaseDetail(purchase_id=p1.id, product_id=product.id, lot_number="C-100",
                           quantity=lot_qty_100, price_bs=1, expiration_date=date(2026, 1, 15)),
            PurchaseDetail(purchase_id=p2.id, product_id=product.id, lot_number="C-101",
                           quantity=lot_qty_101, price_bs=1, expiration_date=date(2026, 6, 1)),
        ])
        db.session.commit()

        return {
            "origin": central, "dest": loc_dest, "product": product,
            "inventory": inv, "user": user, "user_id": user.id,
        }

    def _lots(self, product, origin):
        return MovementDispatchRepository.get_product_lots_available(origin.id, product.id)[1]

    # =========================================================================
    # CASO 1: EMISIÓN MANUAL OK -> asienta salida + crea detalle con lote
    # =========================================================================
    def test_emision_despacho_lote_manual_ok(self):
        env = self._seed()

        items = [{
            "product_id": env["product"].id,
            "quantity": 20.00,
            "lot_number": "L-100",
            "expiration_date": "2026-01-15",
        }]
        mov = MovementDispatchRepository.create_dispatch_transaction(
            env["origin"].id, env["dest"].id, env["user_id"], items
        )

        db.session.commit()
        db.session.refresh(env["inventory"])

        self.assertEqual(mov.type, "DESPACHO")
        self.assertEqual(mov.status, "EN_TRANSITO")
        self.assertEqual(float(env["inventory"].current_quantity), 130.00)
        self.assertEqual(float(env["inventory"].transit_quantity), 20.00)

        detail = MovementDetail.query.filter_by(movement_id=mov.id).first()
        self.assertIsNotNone(detail)
        self.assertEqual(detail.lot_number, "L-100")
        self.assertEqual(float(detail.quantity), 20.00)

    # =========================================================================
    # CASO 2: LOTE INEXISTENTE / SIN DISPONIBILIDAD -> rechazado
    # =========================================================================
    def test_lote_inexistente_rechazado(self):
        env = self._seed()

        items = [{
            "product_id": env["product"].id,
            "quantity": 10.00,
            "lot_number": "L-999",
        }]
        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.create_dispatch_transaction(
                env["origin"].id, env["dest"].id, env["user_id"], items
            )
        self.assertIn("no existe o no posee disponibilidad", str(ctx.exception))
        db.session.rollback()

    # =========================================================================
    # CASO 3: EXCEDER EL SALDO NETO DEL LOTE -> rechazado aunque el global alcance
    # =========================================================================
    def test_exceso_sobre_saldo_del_lote_rechazado(self):
        env = self._seed(lot_qty_100=50.0, lot_qty_101=100.0)

        items = [{
            "product_id": env["product"].id,
            "quantity": 60.00,
            "lot_number": "L-100",
        }]
        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.create_dispatch_transaction(
                env["origin"].id, env["dest"].id, env["user_id"], items
            )
        self.assertIn("solo dispone de", str(ctx.exception))
        db.session.rollback()

    # =========================================================================
    # CASO 4: DOS RENGLONES SOBRE EL MISMO LOTE -> reserva conjunta
    # =========================================================================
    def test_renglones_duplicados_mismo_lote_no_exceden_juntos(self):
        env = self._seed(lot_qty_100=50.0, lot_qty_101=100.0)

        # 30 + 30 = 60 > 50 disponible del lote → rechazado
        items = [
            {"product_id": env["product"].id, "quantity": 30.00, "lot_number": "L-100"},
            {"product_id": env["product"].id, "quantity": 30.00, "lot_number": "L-100"},
        ]
        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.create_dispatch_transaction(
                env["origin"].id, env["dest"].id, env["user_id"], items
            )
        self.assertIn("solo dispone de", str(ctx.exception))
        db.session.rollback()

        # 20 + 20 = 40 <= 50 disponible del lote → ambos deben pasar
        items_ok = [
            {"product_id": env["product"].id, "quantity": 20.00, "lot_number": "L-100"},
            {"product_id": env["product"].id, "quantity": 20.00, "lot_number": "L-100"},
        ]
        mov = MovementDispatchRepository.create_dispatch_transaction(
            env["origin"].id, env["dest"].id, env["user_id"], items_ok
        )
        db.session.commit()

        details = MovementDetail.query.filter_by(movement_id=mov.id).all()
        self.assertEqual(len(details), 2)
        self.assertEqual(sum(float(d.quantity) for d in details), 40.00)

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 110.00)
        self.assertEqual(float(env["inventory"].transit_quantity), 40.00)

    # =========================================================================
    # CASO 5: AUDITORÍA DE CONSUMO SIN product_id YA NO CONTAMINA EL LOTE
    # =========================================================================
    def test_audit_consumo_sin_producto_no_contamina(self):
        env = self._seed(lot_qty_100=50.0, lot_qty_101=100.0)

        orphan = AuditLog(
            affected_table="inventory",
            action="GASTO_COCINA",
            severity="NORMAL",
            user_id=env["user_id"],
            location_id=env["origin"].id,
            timestamp=datetime.now(),
            changed_data={
                "lot_number": "L-100",
                "quantity_changed": 500.0,
                "product_id": None,
            }
        )
        db.session.add(orphan)
        db.session.commit()

        lots = self._lots(env["product"], env["origin"])
        l100 = next(l for l in lots if l["lot_number"] == "L-100")
        self.assertEqual(l100["available_quantity"], 50.0)

    # =========================================================================
    # CASO 5B: LA MISMA CONTAMINACIÓN EN LA SEDE CENTRAL (entradas por compras)
    # =========================================================================
    def test_audit_consumo_sin_producto_central_no_contamina(self):
        env = self._seed_central(lot_qty_100=50.0, lot_qty_101=100.0)

        orphan = AuditLog(
            affected_table="inventory",
            action="GASTO_COCINA",
            severity="NORMAL",
            user_id=env["user_id"],
            location_id=env["origin"].id,
            timestamp=datetime.now(),
            changed_data={
                "lot_number": "C-100",
                "quantity_changed": 500.0,
                "product_id": None,
            }
        )
        db.session.add(orphan)
        db.session.commit()

        lots = self._lots(env["product"], env["origin"])
        c100 = next(l for l in lots if l["lot_number"] == "C-100")
        self.assertEqual(c100["available_quantity"], 50.0)

    # =========================================================================
    # CASO 6: changed_data MALFORMADO -> no tumba la consulta (sin 500)
    # =========================================================================
    def test_changed_data_malformado_no_tumba_consulta(self):
        env = self._seed(lot_qty_100=50.0, lot_qty_101=100.0)

        bad = AuditLog(
            affected_table="inventory",
            action="MERMA",
            severity="NORMAL",
            user_id=env["user_id"],
            location_id=env["origin"].id,
            timestamp=datetime.now(),
            changed_data={"lot_number": "L-101", "quantity_changed": "mucho", "product_id": "abc"},
        )
        db.session.add(bad)
        db.session.commit()

        lots = self._lots(env["product"], env["origin"])
        self.assertEqual(len(lots), 2)
        l100 = next(l for l in lots if l["lot_number"] == "L-100")
        self.assertEqual(l100["available_quantity"], 50.0)

    # =========================================================================
    # CASO 7: CANCELACIÓN SOLO PARA DESPACHOS
    # =========================================================================
    def test_cancelacion_rechaza_movimiento_no_despacho(self):
        env = self._seed()

        traslado = Movement(
            type="TRASLADO",
            origin_location_id=env["origin"].id,
            destination_location_id=env["dest"].id,
            status="EN_TRANSITO",
            user_id=env["user_id"],
            date=datetime.now(),
        )
        db.session.add(traslado)
        db.session.commit()

        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.cancel_dispatch_transaction(
                traslado.id, env["user_id"], "prueba"
            )
        self.assertIn("Solo los despachos", str(ctx.exception))
        db.session.rollback()

    # =========================================================================
    # CASO 8: DESPACHO SIN LOTE -> rechazado
    # =========================================================================
    def test_emision_sin_lote_rechazada(self):
        env = self._seed()

        items = [{"product_id": env["product"].id, "quantity": 10.00, "lot_number": ""}]
        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.create_dispatch_transaction(
                env["origin"].id, env["dest"].id, env["user_id"], items
            )
        self.assertIn("Debe especificar un lote", str(ctx.exception))
        db.session.rollback()

    # =========================================================================
    # CASO 9: PRECANCELACIÓN -> 404 cuando el movimiento no existe
    # =========================================================================
    def test_precancellation_movimiento_inexistente_404(self):
        env = self._seed()
        res, code = MovementDispatchService.execute_precancellation(env["user"], 999999, "motivo")
        self.assertEqual(code, 404)
        self.assertFalse(res["success"])
        self.assertIn("no existe", res["errors"][0])

    # =========================================================================
    # CASO 10: PRECANCELACIÓN EXITOSA -> revierte stock y transición
    # =========================================================================
    def test_precancellation_exitosa_revierte_stock(self):
        env = self._seed(lot_qty_100=50.0, lot_qty_101=100.0)

        # Se emite un despacho de 20 sobre el lote L-100.
        items = [{
            "product_id": env["product"].id,
            "quantity": 20.00,
            "lot_number": "L-100",
        }]
        mov = MovementDispatchRepository.create_dispatch_transaction(
            env["origin"].id, env["dest"].id, env["user_id"], items
        )
        db.session.commit()
        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 130.00)
        self.assertEqual(float(env["inventory"].transit_quantity), 20.00)

        # Se cancela vía el servicio.
        res, code = MovementDispatchService.execute_precancellation(
            env["user"], mov.id, "reposición incorrecta"
        )
        self.assertEqual(code, 200)
        self.assertTrue(res["success"])

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 150.00)
        self.assertEqual(float(env["inventory"].transit_quantity), 0.00)

        db.session.refresh(mov)
        self.assertEqual(mov.status, "CANCELADO_EMISOR")


if __name__ == "__main__":
    unittest.main()