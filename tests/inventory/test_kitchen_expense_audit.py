"""
Auditoría de Gastos de Cocina.

Cubre el visor de consumos (GASTO_COCINA/CONSUMO_COCINA), su valorización al
último costo de compra y la edición/anulación/activación con los mismos límites
que AuditInventory (ventanas de tiempo, sedes, roles y stock disponible).

Nota: usa la base DE PRUEBA (ph_test), nunca la base real (ph).
"""
import json
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
    AuditLog, Inventory, Location, Movement, MovementDetail, Product,
    Purchase, PurchaseDetail, Role, User,
)
from app.inventory.requests.kitchen_expense_audit_validators import (  # noqa: E402
    validate_kitchen_expense_action,
)
from app.inventory.services.kitchen_expense_audit_service import (  # noqa: E402
    get_kitchen_expense_counts,
    get_kitchen_expense_entries,
    process_kitchen_expense_action,
)
from app.inventory.services.register_consumption_service import (  # noqa: E402
    register_consumption,
)


class DummyUser:
    def __init__(self, user_id, role_id=1):
        self.id = user_id
        self.role_id = role_id


class KitchenExpenseAuditTest(unittest.TestCase):

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
    def _seed(self, stock=100.0, with_purchase=False):
        role_admin = Role(id=1, name="Administrator")
        role_ops = Role(id=4, name="Operations")
        role_fin = Role(id=6, name="Finance")
        db.session.add_all([role_admin, role_ops, role_fin])
        db.session.flush()

        admin = User(name="Admin", email="admin@kea.test",
                     password_hash="x", role_id=1)
        finance = User(name="Finanzas", email="fin@kea.test",
                       password_hash="x", role_id=6)
        db.session.add_all([admin, finance])
        db.session.flush()

        central = Location(name="Sede Central", state="Caracas")
        sede_a = Location(name="Sede A", state="Caracas")
        db.session.add_all([central, sede_a])
        db.session.flush()

        product = Product(name="Tomate", sku="TOM-KEA",
                          unit_of_measure="kg", is_active=True)
        db.session.add(product)
        db.session.flush()

        db.session.add(Inventory(
            location_id=sede_a.id, product_id=product.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20.0,
        ))
        mov = Movement(
            type="TRASLADO", origin_location_id=central.id,
            destination_location_id=sede_a.id, status="COMPLETED",
            user_id=admin.id, date=datetime.now(),
        )
        db.session.add(mov)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=mov.id, product_id=product.id, lot_number="L-001",
            quantity=stock, received_quantity=stock, missing_quantity=0.00,
            expiration_date=None,
        ))

        if with_purchase:
            compra = Purchase(
                user_id=admin.id, supplier_id=None, currency="USD",
                status="COMPLETADO", purchase_date=datetime.now(),
                invoice_url="",
            )
            db.session.add(compra)
            db.session.flush()
            db.session.add(PurchaseDetail(
                purchase_id=compra.id, product_id=product.id,
                lot_number="L-001", quantity=stock,
                foreign_price=10.00, price_bs=0.00,
            ))

        db.session.commit()
        return {
            "admin": admin, "finance": finance,
            "central": central, "sede_a": sede_a,
            "product": product, "stock": stock,
        }

    def _inv(self, env):
        return Inventory.query.filter_by(
            location_id=env["sede_a"].id,
            product_id=env["product"].id,
        ).first()

    def _consume(self, env, qty=30.0, notes="Prueba"):
        res = register_consumption(env["sede_a"].id, [
            {"product_id": env["product"].id, "quantity": qty,
             "lot_number": "L-001", "notes": notes},
        ], env["admin"].id)
        self.assertTrue(res["success"], res)
        log = (AuditLog.query
               .filter(AuditLog.action == 'GASTO_COCINA')
               .order_by(AuditLog.id.desc()).first())
        return log.id

    def _direct_log(self, env, qty=-30, prev=100.0, new=70.0, action="GASTO_COCINA",
                    location=None, user=None, ts=None, lot="L-001"):
        log = AuditLog(
            user_id=(user or env["admin"]).id,
            location_id=(location or env["sede_a"]).id,
            action=action,
            severity="NORMAL",
            timestamp=ts or datetime.now(),
            changed_data=json.dumps({
                "product_id": env["product"].id,
                "product_name": env["product"].name,
                "lot_number": lot,
                "previous_quantity": prev,
                "new_quantity": new,
                "quantity_changed": qty,
                "notes": "Log directo de prueba",
            }),
        )
        db.session.add(log)
        db.session.commit()
        return log.id

    # ------------------------------------------------------------------
    # ROUTE Y VISOR
    # ------------------------------------------------------------------
    def test_route_existe_y_requiere_sesion(self):
        client = self.app.test_client()
        res = client.get("/inventory/expenses/audit")
        self.assertEqual(res.status_code, 302)

    def test_visor_lista_consumos_base(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["id"], log_id)
        self.assertEqual(entry["product"], "Tomate")
        self.assertEqual(entry["qty"], -30.0)
        self.assertTrue(entry["can_manage"])

    def test_visor_valoriza_monto_con_ultimo_costo(self):
        env = self._seed(with_purchase=True)
        self._consume(env, 5.0)
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertEqual(entries[0]["amount"], Decimal("50.00"))
        self.assertEqual(entries[0]["currency"], "USD")

    def test_visor_sin_stock_base_para_valorizar(self):
        env = self._seed()
        self._consume(env, 5.0)
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertIsNone(entries[0]["amount"])

    def test_visor_no_admin_limita_por_sedes(self):
        env = self._seed()
        self._consume(env, 10.0)
        role_ops = DummyUser(user_id=env["admin"].id, role_id=4)
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, role_ops, is_admin=False)
        # Sin sedes asignadas no ve nada.
        self.assertEqual(entries, [])

    def test_counts_por_pestanas(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)
        process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="EDITAR",
            new_quantity_requested=15,
            justification_notes="Se gastaron menos",
        )
        counts = get_kitchen_expense_counts({"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertEqual(counts["gastos"], 1)
        self.assertEqual(counts["ajustes"], 1)
        ajustes = get_kitchen_expense_entries(
            {"tab": "ajustes"}, env["admin"], is_admin=True)
        self.assertEqual(len(ajustes), 1)
        self.assertEqual(ajustes[0]["action"], "AJUSTE_GASTO_COCINA")

    def test_gasto_corregido_muestra_disponible_actual(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)  # 100 -> 70
        process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="EDITAR",
            new_quantity_requested=15,
            justification_notes="Se gastaron menos",
        )
        self.assertEqual(float(self._inv(env).current_quantity), 85.0)
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        # El disponible mostrado es el vigente (85), no el histórico posterior al gasto (70).
        self.assertEqual(float(entry["current_qty"]), 85.0)
        # El registro corregido enlaza con el ajuste real, no con None.
        ajuste = (AuditLog.query
                  .filter(AuditLog.action == 'AJUSTE_GASTO_COCINA')
                  .order_by(AuditLog.id.desc()).first())
        self.assertEqual(entry["target_log_id"], ajuste.id)

    def test_gasto_sin_inventario_cae_a_ultimo_disponible(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)
        self._inv(env).current_quantity = 100.5
        db.session.commit()
        entries = get_kitchen_expense_entries(
            {"tab": "gastos"}, env["admin"], is_admin=True)
        self.assertEqual(float(entries[0]["current_qty"]), 100.5)

    # ------------------------------------------------------------------
    # EDICIÓN CON LÍMITES (portada de AuditInventory)
    # ------------------------------------------------------------------
    def test_editar_corrige_cantidad_y_restaura_stock(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)
        self.assertEqual(float(self._inv(env).current_quantity), 70.0)

        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="EDITAR",
            new_quantity_requested=15,
            justification_notes="Se gastaron 15, no 30",
        )
        self.assertTrue(res["success"], res)
        self.assertEqual(float(self._inv(env).current_quantity), 85.0)

        original = AuditLog.query.get(log_id)
        self.assertEqual(original.severity, "EDITADO")
        ajuste = (AuditLog.query
                  .filter(AuditLog.action == 'AJUSTE_GASTO_COCINA')
                  .order_by(AuditLog.id.desc()).first())
        self.assertIsNotNone(ajuste)
        self.assertEqual(ajuste.changed_data["quantity_changed"], 15.0)

    def test_anular_restituye_el_stock_completo(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)

        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ANULAR",
            justification_notes="Error de registro",
        )
        self.assertTrue(res["success"], res)
        self.assertEqual(float(self._inv(env).current_quantity), 100.0)

        original = AuditLog.query.get(log_id)
        self.assertEqual(original.severity, "ANULADO")
        rev = (AuditLog.query
               .filter(AuditLog.action == 'REVERSION_GASTO_COCINA')
               .order_by(AuditLog.id.desc()).first())
        self.assertIsNotNone(rev)

    def test_activar_anulado_vuelve_a_descontar(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)
        process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ANULAR",
            justification_notes="Anulación de prueba",
        )
        self.assertEqual(float(self._inv(env).current_quantity), 100.0)

        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ACTIVAR",
            justification_notes="Se confirma el gasto",
        )
        self.assertTrue(res["success"], res)
        self.assertEqual(float(self._inv(env).current_quantity), 70.0)
        self.assertEqual(AuditLog.query.get(log_id).severity, "NORMAL")

    def test_expirado_30_dias_admin_bloqueado(self):
        env = self._seed()
        log_id = self._direct_log(
            env, ts=datetime.now() - timedelta(days=31))
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ANULAR",
            justification_notes="Intento tardío",
        )
        self.assertFalse(res["success"])
        self.assertIn("30 días", res["message"])

    def test_expirado_24h_sin_ser_admin_bloqueado(self):
        env = self._seed()
        log_id = self._direct_log(
            env, ts=datetime.now() - timedelta(hours=25))
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["finance"].id, role_id=2),
            action_type="ANULAR",
            justification_notes="Intento tardío",
        )
        self.assertFalse(res["success"])
        self.assertIn("24 horas", res["message"])

    def test_finanzas_solo_lectura(self):
        env = self._seed()
        log_id = self._consume(env, 10.0)
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["finance"].id, role_id=6),
            action_type="EDITAR",
            new_quantity_requested=5,
            justification_notes="Quiere corregir",
        )
        self.assertFalse(res["success"])
        self.assertIn("solo lectura", res["message"])

    def test_almacen_general_no_admite_modificaciones(self):
        env = self._seed()
        almacen = Location(id=1, name="Almacén General", state="Zulia")
        db.session.add(almacen)
        db.session.commit()
        log_id = self._direct_log(env, location=almacen)
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ANULAR",
            justification_notes="Intento en central",
        )
        self.assertFalse(res["success"])
        self.assertIn("Almacén General", res["message"])

    def test_no_admite_registros_compensatorios(self):
        env = self._seed()
        log_id = self._direct_log(env, action="AJUSTE_GASTO_COCINA", qty=15,
                                  prev=70.0, new=85.0)
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="ANULAR",
            justification_notes="Intentar tocar un ajuste",
        )
        self.assertFalse(res["success"])
        self.assertIn("inmutables", res["message"])

    def test_ajuste_negativo_exige_stock_suficiente(self):
        env = self._seed()
        log_id = self._consume(env, 30.0)  # stock 70
        res = process_kitchen_expense_action(
            log_id=log_id,
            current_user=DummyUser(user_id=env["admin"].id, role_id=1),
            action_type="EDITAR",
            new_quantity_requested=150,  # exige +120 del stock de 70
            justification_notes="Cantidad imposible",
        )
        self.assertFalse(res["success"])
        self.assertIn("excede el stock", res["message"])
        self.assertEqual(float(self._inv(env).current_quantity), 70.0)

    # ------------------------------------------------------------------
    # VALIDADOR
    # ------------------------------------------------------------------
    def test_validator_contrato_obligatorio(self):
        valid = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "ANULAR", "notes": "Motivo",
        })
        self.assertTrue(valid["is_valid"])

        invalid = validate_kitchen_expense_action({})
        self.assertFalse(invalid["is_valid"])

        missing = validate_kitchen_expense_action({
            "action_type": "ANULAR", "notes": "Motivo",
        })
        self.assertIn("log_id", missing["errors"])

        bad_action = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "BORRAR", "notes": "Motivo",
        })
        self.assertIn("action_type", bad_action["errors"])

        no_notes = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "ANULAR",
        })
        self.assertIn("notes", no_notes["errors"])

    def test_validator_editar_exige_cantidad_positiva(self):
        empty = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "EDITAR", "notes": "Motivo",
        })
        self.assertIn("new_quantity", empty["errors"])

        zero = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "EDITAR",
            "notes": "Motivo", "new_quantity": 0,
        })
        self.assertIn("new_quantity", zero["errors"])

        huge = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "EDITAR",
            "notes": "Motivo", "new_quantity": 9999999.99,
        })
        self.assertIn("new_quantity", huge["errors"])

        ok = validate_kitchen_expense_action({
            "log_id": "3", "action_type": "EDITAR",
            "notes": "Motivo", "new_quantity": 15.5,
        })
        self.assertTrue(ok["is_valid"])


if __name__ == "__main__":
    unittest.main()