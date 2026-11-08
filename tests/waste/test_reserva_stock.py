"""
Reserva de stock para mermas PENDIENTES (reserved_quantity).

Protege el stock congelado por una merma pendiente de aprobación: cocina,
traslados y ediciones NO pueden gastar/mover lo reservado hasta que el Admin
decide (aprobar descuenta y libera; rechazar/cancelar libera sin descontar).

Nota: usa la base DE PRUEBA (ph_test), nunca la base real (ph).
"""
import os
import unittest
from datetime import datetime

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
    Inventory, Location, Movement, MovementDetail, Product, Role, User,
    Waste, WasteType,
)
from app.waste.services.register_waste_service import register_waste  # noqa: E402
from app.waste.services.waste_approvals_service import (  # noqa: E402
    cancel_waste, decidir_lineas,
)
from app.waste.services.waste_edit_service import WasteEditService  # noqa: E402
from app.inventory.services.register_consumption_service import register_consumption  # noqa: E402
from app.logistics.repositories.movement_dispatch_repository import MovementDispatchRepository  # noqa: E402


class ReservaStockTest(unittest.TestCase):

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

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _seed(self, stock=100.0):
        """Sede A (mermas/cocina) y Sede B (origen de traslado), ambos con el
        mismo producto y su lote L-001 recibido (MovementDetail COMPLETED).
        Usuarios: admin1 (autor de mermas), admin2 (resuelve) y un Admin retail
        para consumo. El tipo TEMPERATURA (requires_approval) SIEMPRE deja la
        merma PENDIENTE."""
        role_admin = Role(id=1, name="Administrator")
        db.session.add(role_admin)
        db.session.flush()

        admin1 = User(name="Admin Uno", email="admin1@reserva.test",
                      password_hash="x", role_id=role_admin.id)
        admin2 = User(name="Admin Dos", email="admin2@reserva.test",
                      password_hash="x", role_id=role_admin.id)
        db.session.add_all([admin1, admin2])
        db.session.flush()

        central = Location(name="Sede Central", state="Caracas")
        sede_a = Location(name="Sede A", state="Caracas")
        sede_b = Location(name="Sede B", state="Caracas")
        db.session.add_all([central, sede_a, sede_b])
        db.session.flush()

        product = Product(name="Tomate", sku="TOM-RES", unit_of_measure="kg", is_active=True)
        db.session.add(product)
        db.session.flush()

        for sede in (sede_a, sede_b):
            db.session.add(Inventory(
                location_id=sede.id, product_id=product.id,
                current_quantity=stock, transit_quantity=0.0, min_stock=20.0,
            ))
            mov = Movement(
                type="TRASLADO", origin_location_id=central.id,
                destination_location_id=sede.id, status="COMPLETED",
                user_id=admin1.id, date=datetime.now(),
            )
            db.session.add(mov)
            db.session.flush()
            db.session.add(MovementDetail(
                movement_id=mov.id, product_id=product.id, lot_number="L-001",
                quantity=stock, received_quantity=stock, missing_quantity=0.00,
                expiration_date=None,
            ))

        wt = WasteType(name="Temperatura", code="TEMPERATURA",
                       requires_approval=True, severity="MEDIA",
                       is_active=True)
        db.session.add(wt)
        db.session.flush()
        db.session.commit()

        return {
            "admin1": admin1, "admin2": admin2,
            "sede_a": sede_a, "sede_b": sede_b,
            "product": product, "waste_type": wt,
            "stock": stock,
        }

    def _inv(self, sede, product):
        return Inventory.query.filter_by(
            location_id=sede.id, product_id=product.id
        ).first()

    def _register(self, env, qty, user_id, request_id):
        return register_waste(
            user_id=user_id,
            location_id=env["sede_a"].id,
            items=[{
                "product_id": env["product"].id,
                "lot_number": "L-001",
                "quantity": qty,
                "waste_type_id": env["waste_type"].id,
            }],
            evidence_url=None,
            notes="Merma de prueba",
            request_id=request_id,
        )

    def _detail(self, waste):
        return waste.details[0]

    # ------------------------------------------------------------------
    # MERMAS: REGISTRO PENDIENTE -> CONGELA
    # ------------------------------------------------------------------
    def test_merma_pendiente_congela_stock_y_no_descuenta(self):
        env = self._seed()
        res = self._register(env, 10.0, env["admin1"].id, "REQ-01")
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 100.0)
        self.assertEqual(float(inv.reserved_quantity), 10.0)
        self.assertEqual(float(inv.available_quantity()), 90.0)

    def test_merma_pendiente_que_excede_disponible_es_rechazada(self):
        env = self._seed()
        r1 = self._register(env, 60.0, env["admin1"].id, "REQ-11")
        self.assertEqual(r1["status"], "PENDIENTE")
        r2 = self._register(env, 50.0, env["admin1"].id, "REQ-12")
        self.assertFalse(r2["success"])
        self.assertIn("Stock insuficiente", r2["message"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.reserved_quantity), 60.0)
        self.assertEqual(float(inv.current_quantity), 100.0)

    def test_merma_aprobada_descuenta_y_libera_reserva(self):
        env = self._seed()
        res = self._register(env, 10.0, env["admin1"].id, "REQ-21")
        waste = Waste.query.get(res["waste_id"])
        d = self._detail(waste)
        r = decidir_lineas(
            waste.id, env["admin2"].id,
            [{"detail_id": d.id, "decision": "aprobar"}],
        )
        self.assertTrue(r["success"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 90.0)
        self.assertEqual(float(inv.reserved_quantity), 0.0)

    def test_aprobar_merma_cuyo_reserva_deja_apisparable_menor_a_la_merma(self):
        # Regresión: aprobar una merma cuya PROPIA reserva deja
        # (current - transit - reserved) < quantity. Esa reserva es la que se
        # consume al aprobar, así que debe poder aprobarse (ej: 40 físicos en la
        # sede y la merma pendiente congeló 30 -> aprobar los 30 debe funcionar).
        env = self._seed(stock=40.0)
        res = self._register(env, 30.0, env["admin1"].id, "REQ-80")
        self.assertEqual(res["status"], "PENDIENTE")
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 40.0)
        self.assertEqual(float(inv.reserved_quantity), 30.0)

        waste = Waste.query.get(res["waste_id"])
        d = self._detail(waste)
        r = decidir_lineas(
            waste.id, env["admin2"].id,
            [{"detail_id": d.id, "decision": "aprobar"}],
        )
        self.assertTrue(r["success"], r)
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 10.0)
        self.assertEqual(float(inv.reserved_quantity), 0.0)

    def test_merma_rechazada_libera_reserva_sin_descontar(self):
        env = self._seed()
        res = self._register(env, 10.0, env["admin1"].id, "REQ-31")
        waste = Waste.query.get(res["waste_id"])
        d = self._detail(waste)
        r = decidir_lineas(
            waste.id, env["admin2"].id,
            [{"detail_id": d.id, "decision": "rechazar",
              "reason": "El producto no presenta novedad y puede usarse en cocina."}],
        )
        self.assertTrue(r["success"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 100.0)
        self.assertEqual(float(inv.reserved_quantity), 0.0)

    def test_decision_parcial_aprobar_y_rechazar_libera_todo(self):
        # Misma merma con dos líneas del mismo producto: una se aprueba y la
        # otra se rechaza. La reserva se libera completa, el stock se descuenta
        # solo por lo aprobado y la cabecera queda APROBADO_PARCIAL.
        env = self._seed()
        res = register_waste(
            user_id=env["admin1"].id,
            location_id=env["sede_a"].id,
            items=[
                {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 10.0,
                 "waste_type_id": env["waste_type"].id},
                {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0,
                 "waste_type_id": env["waste_type"].id},
            ],
            evidence_url=None,
            notes="Merma de prueba",
            request_id="REQ-34",
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")

        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.reserved_quantity), 15.0)

        waste = Waste.query.get(res["waste_id"])
        d1, d2 = waste.details[0], waste.details[1]
        r = decidir_lineas(
            waste.id, env["admin2"].id,
            [
                {"detail_id": d1.id, "decision": "aprobar"},
                {"detail_id": d2.id, "decision": "rechazar",
                 "reason": "Se rechaza la parte; la harina sigue apta para cocina."},
            ],
        )
        self.assertTrue(r["success"])
        self.assertEqual(r.get("finalizado"), True)
        self.assertEqual(waste.status, "APROBADO_PARCIAL")
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 90.0)
        self.assertEqual(float(inv.reserved_quantity), 0.0)

    def test_cancelar_merma_libera_reserva(self):
        env = self._seed()
        res = self._register(env, 10.0, env["admin1"].id, "REQ-41")
        waste = Waste.query.get(res["waste_id"])
        r = cancel_waste(waste.id, env["admin1"].id, "Me equivoqué, se usará en cocina hoy.")
        self.assertTrue(r["success"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 100.0)
        self.assertEqual(float(inv.reserved_quantity), 0.0)

    # ------------------------------------------------------------------
    # MERMAS: EDICIÓN PENDIENTE -> DELTA DE RESERVA
    # ------------------------------------------------------------------
    def test_editar_merma_pendiente_ajusta_reserva_y_valida_disponible(self):
        env = self._seed()
        r1 = self._register(env, 5.0, env["admin1"].id, "REQ-51")
        # Segunda merma pendiente congelando más; juntas reservan 60.
        r2 = self._register(env, 55.0, env["admin1"].id, "REQ-52")
        self.assertEqual(r2["status"], "PENDIENTE")

        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.reserved_quantity), 60.0)

        # Reducir la primera de 5 a 3 -> libera 2.
        payload = {
            "waste_type_id": env["waste_type"].id,
            "notes": "Corrección",
            "lines": [{
                "product_id": env["product"].id,
                "lot_number": "L-001",
                "quantity": 3.0,
                "expiration_date": None,
            }],
        }
        ok, status = WasteEditService.edit_pending_waste(r1["waste_id"], payload, env["admin1"].id, True)
        self.assertEqual(status, 200)
        self.assertTrue(ok["success"])
        self.assertEqual(float(self._inv(env["sede_a"], env["product"]).reserved_quantity), 58.0)

        # Subir la primera a 12 -> si la reserva total (55+12=67) aún cabe, pasa.
        payload2 = {
            "waste_type_id": env["waste_type"].id,
            "notes": "Corrección 2",
            "lines": [{
                "product_id": env["product"].id,
                "lot_number": "L-001",
                "quantity": 12.0,
                "expiration_date": None,
            }],
        }
        ok2, status2 = WasteEditService.edit_pending_waste(r1["waste_id"], payload2, env["admin1"].id, True)
        self.assertEqual(status2, 200)
        self.assertTrue(ok2["success"])
        self.assertEqual(float(self._inv(env["sede_a"], env["product"]).reserved_quantity), 67.0)

        # Subir la primera por encima del disponible del lote (100 físico menos
        # 55+12 ya comprometidos = 33) -> 400.
        payload3 = {
            "waste_type_id": env["waste_type"].id,
            "notes": "Corrección 3",
            "lines": [{
                "product_id": env["product"].id,
                "lot_number": "L-001",
                "quantity": 46.0,
                "expiration_date": None,
            }],
        }
        fail, status3 = WasteEditService.edit_pending_waste(r1["waste_id"], payload3, env["admin1"].id, True)
        self.assertEqual(status3, 400)
        self.assertIn("saldo disponible", fail.get("message", ""))
        self.assertEqual(float(self._inv(env["sede_a"], env["product"]).reserved_quantity), 67.0)

    def test_editar_eliminando_una_linea_libera_la_reserva(self):
        env = self._seed()
        # Merma con dos líneas del mismo producto (5 + 7 = 12 reservados).
        res = register_waste(
            user_id=env["admin1"].id,
            location_id=env["sede_a"].id,
            items=[
                {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0,
                 "waste_type_id": env["waste_type"].id},
                {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 7.0,
                 "waste_type_id": env["waste_type"].id},
            ],
            evidence_url=None,
            notes="Merma de prueba",
            request_id="REQ-55",
        )
        self.assertEqual(res["status"], "PENDIENTE")
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.reserved_quantity), 12.0)

        # Editar dejando SOLO la línea de 7: la línea de 5 desaparece y su
        # reserva se libera. La unión old/new de productos dispara el delta.
        payload = {
            "waste_type_id": env["waste_type"].id,
            "notes": "Corrección",
            "lines": [{
                "product_id": env["product"].id,
                "lot_number": "L-001",
                "quantity": 7.0,
                "expiration_date": None,
            }],
        }
        ok, status = WasteEditService.edit_pending_waste(res["waste_id"], payload, env["admin1"].id, True)
        self.assertEqual(status, 200)
        self.assertTrue(ok["success"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.reserved_quantity), 7.0)
        self.assertEqual(float(inv.current_quantity), 100.0)

    # ------------------------------------------------------------------
    # COCINA: no gasta el stock congelado
    # ------------------------------------------------------------------
    def test_consumo_cocina_no_gasta_stock_congelado(self):
        env = self._seed()
        self._register(env, 60.0, env["admin1"].id, "REQ-61")  # congelan 60

        over = register_consumption(env["sede_a"].id, [
            {"product_id": env["product"].id, "quantity": 50.0, "lot_number": "L-001"},
        ], env["admin1"].id)
        self.assertFalse(over["success"])
        self.assertIn("Stock insuficiente", over["message"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 100.0)
        self.assertEqual(float(inv.reserved_quantity), 60.0)

        ok = register_consumption(env["sede_a"].id, [
            {"product_id": env["product"].id, "quantity": 40.0, "lot_number": "L-001"},
        ], env["admin1"].id)
        self.assertTrue(ok["success"])
        inv = self._inv(env["sede_a"], env["product"])
        self.assertEqual(float(inv.current_quantity), 60.0)
        self.assertEqual(float(inv.reserved_quantity), 60.0)

    # ------------------------------------------------------------------
    # TRASLADOS: no mueven el stock congelado
    # ------------------------------------------------------------------
    def test_despacho_no_mueve_stock_congelado(self):
        env = self._seed()
        r = self._register(env, 60.0, env["admin1"].id, "REQ-71")
        self.assertEqual(r["status"], "PENDIENTE")
        inv_origin = self._inv(env["sede_b"], env["product"])
        inv_origin.reserved_quantity = 60.0
        db.session.commit()

        payload = [{
            "product_id": env["product"].id,
            "quantity": 70.0,
            "lot_number": "L-001",
        }]
        with self.assertRaises(ValueError) as ctx:
            MovementDispatchRepository.create_dispatch_transaction(
                env["sede_b"].id, env["sede_a"].id, env["admin1"].id, payload
            )
        self.assertIn("Stock insuficiente", str(ctx.exception))

        db.session.rollback()
        payload2 = [{
            "product_id": env["product"].id,
            "quantity": 40.0,
            "lot_number": "L-001",
        }]
        movement = MovementDispatchRepository.create_dispatch_transaction(
            env["sede_b"].id, env["sede_a"].id, env["admin1"].id, payload2
        )
        db.session.commit()
        inv_origin = self._inv(env["sede_b"], env["product"])
        self.assertEqual(float(inv_origin.current_quantity), 60.0)
        self.assertEqual(float(inv_origin.transit_quantity), 40.0)
        self.assertEqual(float(inv_origin.reserved_quantity), 60.0)


if __name__ == "__main__":
    unittest.main()