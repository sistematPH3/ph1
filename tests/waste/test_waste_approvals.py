# =============================================================================
# PRUEBA AUTOMÁTICA DE LA BANDEJA DE APROBACIÓN DE MERMAS (Parte 3 + Parte 5)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Aprobar una merma PENDIENTE descuenta stock (current_quantity), marca
#      APROBADO, crea auditoría NORMAL (event MERMA_APROBADA) y notifica al autor.
#   2) Aprobar exige rol Administrador (otro rol -> PermissionError).
#   3) Aprobar una merma no-pendiente se rechaza sin tocar stock.
#   4) Aprobar con stock insuficiente se aborta sin descontar nada.
#   5) Rechazar una merma PENDIENTE NO toca stock, marca RECHAZADO, crea
#      auditoría ALERTA (event MERMA_RECHAZADA) y notifica al autor.
#   6) La cola de pendientes filtra por sede según el usuario.
#   7) El detalle devuelve líneas con nombre de producto y stock del lote.
#
# Uso (en la carpeta ph1, Linux/Ubuntu):
#   .venv/bin/python -m unittest tests.waste.test_waste_approvals -v
# =============================================================================

import os
import unittest
import json
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
    Inventory, Location, Product, Role, User,
    Waste, WasteDetail, WasteType, AuditLog,
)
from app.models.security_model import Notification  # noqa: E402
from app.waste.services import waste_approvals_service as svc  # noqa: E402
from app.waste.services.waste_audit_service import WasteAuditService  # noqa: E402


class MermaApprovalsTest(unittest.TestCase):

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

    def _seed(self, stock=100.0, qty=10.0):
        """Admin, autor (Operations) y una merma PENDIENTE en una sede."""
        role_admin = Role(name="Administrator")
        role_ops = Role(name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        admin = User(name="Admin", email="admin@test.com",
                     password_hash="x", role_id=role_admin.id)
        author = User(name="Cocinera", email="cocina@test.com",
                      password_hash="x", role_id=role_ops.id)
        loc = Location(name="Sede Test", state="Caracas")
        product = Product(name="Tomate", sku="TOM-W1", unit_of_measure="kg")
        db.session.add_all([admin, author, loc, product])
        db.session.flush()

        inv = Inventory(
            location_id=loc.id, product_id=product.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20
        )
        db.session.add(inv)
        wt = WasteType(name="Vencido", requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc.id, waste_type_id=wt.id, user_id=author.id,
            status="PENDIENTE", total_quantity=qty, notes="Merma de prueba",
            date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-AAA",
            expiration_date=None, quantity=qty, unit_cost=1.0, subtotal_cost=qty,
        ))
        db.session.commit()

        return {
            "admin": admin, "author": author, "loc": loc, "product": product,
            "inventory": inv, "waste": waste, "waste_type": wt,
        }

    def _seed_multi(self, stock=100.0, qty_lote1=10.0, qty_lote2=5.0):
        """Misma infraestructura pero con DOS productos/lotes en la misma merma.

        Permite probar la decisión POR PRODUCTO: aprobar uno y rechazar otro.
        """
        role_admin = Role(name="Administrator")
        role_ops = Role(name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        admin = User(name="Admin", email="admin@test.com",
                     password_hash="x", role_id=role_admin.id)
        author = User(name="Cocinera", email="cocina@test.com",
                      password_hash="x", role_id=role_ops.id)
        loc = Location(name="Sede Test", state="Caracas")
        prod_a = Product(name="Tomate", sku="TOM-W1", unit_of_measure="kg")
        prod_b = Product(name="Cebolla", sku="CEB-W1", unit_of_measure="kg")
        db.session.add_all([admin, author, loc, prod_a, prod_b])
        db.session.flush()

        inv_a = Inventory(
            location_id=loc.id, product_id=prod_a.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20
        )
        inv_b = Inventory(
            location_id=loc.id, product_id=prod_b.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20
        )
        db.session.add_all([inv_a, inv_b])
        wt = WasteType(name="Vencido", requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc.id, waste_type_id=wt.id, user_id=author.id,
            status="PENDIENTE", total_quantity=qty_lote1 + qty_lote2,
            notes="Merma multi-producto", date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=prod_a.id, lot_number="L-AAA",
            expiration_date=None, quantity=qty_lote1, unit_cost=1.0,
            subtotal_cost=qty_lote1,
        ))
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=prod_b.id, lot_number="L-BBB",
            expiration_date=None, quantity=qty_lote2, unit_cost=1.0,
            subtotal_cost=qty_lote2,
        ))
        db.session.commit()

        return {
            "admin": admin, "author": author, "loc": loc,
            "product_a": prod_a, "product_b": prod_b,
            "inventory_a": inv_a, "inventory_b": inv_b,
            "waste": waste, "waste_type": wt,
        }

    # =========================================================================
    # CASO 1: APROBAR -> descuenta stock + APROBADO + auditoría + notificación
    # =========================================================================
    def test_aprobar_descuenta_stock_y_audita(self):
        env = self._seed(stock=100.0, qty=10.0)

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertTrue(res["success"], res)

        db.session.refresh(env["inventory"])
        db.session.refresh(env["waste"])
        self.assertEqual(float(env["inventory"].current_quantity), 90.0)
        self.assertEqual(env["waste"].status, "APROBADO")
        self.assertEqual(env["waste"].approved_by_id, env["admin"].id)
        self.assertIsNotNone(env["waste"].approved_at)

        audit = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.severity, "NORMAL")
        self.assertEqual(audit.user_id, env["admin"].id)
        self.assertEqual(audit.location_id, env["loc"].id)
        changed = json.loads(audit.changed_data) if isinstance(audit.changed_data, str) else audit.changed_data
        self.assertEqual(changed.get("event"), "MERMA_APROBADA")
        self.assertEqual(changed["descuentos_stock"][0]["stock_antes"], 100.0)
        # Las aprobaciones NO deben arrastrar clave motivo_rechazo (evita que la
        # Auditoría de Mermas las clasifique como rechazadas).
        self.assertNotIn("motivo_rechazo", changed)
        # Detalle por línea con su foto y productos normalizados con decisión.
        self.assertIn("evidence_url", changed["decisiones"][0])
        self.assertEqual(changed["productos"][0]["decision"], "APROBADO")
        self.assertEqual(changed["merma_id"], env["waste"].id)

        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_APROBADA"
        ).first()
        self.assertIsNotNone(notif)

    # =========================================================================
    # CASO 2: NO-ADMIN NO PUEDE APROBAR
    # =========================================================================
    def test_no_admin_no_puede_aprobar(self):
        env = self._seed()
        with self.assertRaises(PermissionError):
            svc.approve_waste(env["waste"].id, env["author"].id)
        db.session.rollback()

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)

    # =========================================================================
    # CASO 3: APROBAR UNA MERMA NO-PENDIENTE SE RECHAZA
    # =========================================================================
    def test_aprobar_merma_no_pendiente_se_rechaza(self):
        env = self._seed()
        env["waste"].status = "RECHAZADO"
        db.session.commit()

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertFalse(res["success"])
        self.assertIn("pendientes", res["message"])

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)

    # =========================================================================
    # CASO 4: STOCK INSUFICIENTE -> aborta sin descontar
    # =========================================================================
    def test_stock_insuficiente_aborta(self):
        env = self._seed(stock=5.0, qty=10.0)

        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertFalse(res["success"])
        self.assertIn("Stock insuficiente", res["message"])

        db.session.refresh(env["inventory"])
        self.assertEqual(float(env["inventory"].current_quantity), 5.0)
        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "PENDIENTE")

    # =========================================================================
    # CASO 5: RECHAZAR -> NO toca stock + RECHAZADO + auditoría + notificación
    # =========================================================================
    def test_rechazar_no_toca_stock_y_audita(self):
        env = self._seed(stock=100.0, qty=10.0)

        res = svc.reject_waste(env["waste"].id, env["admin"].id, "Merma inválida, no corresponde.")
        self.assertTrue(res["success"], res)

        db.session.refresh(env["inventory"])
        db.session.refresh(env["waste"])
        self.assertEqual(float(env["inventory"].current_quantity), 100.0)
        self.assertEqual(env["waste"].status, "RECHAZADO")

        audit = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.severity, "ALERTA")
        changed = json.loads(audit.changed_data) if isinstance(audit.changed_data, str) else audit.changed_data
        self.assertEqual(changed.get("event"), "MERMA_RECHAZADA")
        self.assertIn("Merma inválida", changed["motivo_rechazo"])

        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_RECHAZADA"
        ).first()
        self.assertIsNotNone(notif)

    # =========================================================================
    # CASO 6: COLA DE PENDIENTES FILTRA POR SEDE
    # =========================================================================
    def test_cola_pendientes_filtra_por_sede(self):
        env = self._seed()

        # Admin ve la pendiente.
        admin_pending = svc.get_pending_wastes(env["admin"].id)
        self.assertEqual(len(admin_pending), 1)
        self.assertEqual(admin_pending[0]["id"], env["waste"].id)

        # Autor (Operations) sin sede asignada no la ve.
        author_pending = svc.get_pending_wastes(env["author"].id)
        self.assertEqual(author_pending, [])

    # =========================================================================
    # CASO 7: DETALLE DEVUELVE LÍNEAS CON PRODUCTO Y STOCK DEL LOTE
    # =========================================================================
    def test_detalle_con_lineas_y_stock_de_lote(self):
        env = self._seed(stock=100.0, qty=10.0)

        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        self.assertEqual(data["id"], env["waste"].id)
        self.assertEqual(data["location_name"], "Sede Test")
        self.assertEqual(len(data["lines"]), 1)
        line = data["lines"][0]
        self.assertEqual(line["product_name"], "Tomate")
        self.assertEqual(line["lot_number"], "L-AAA")
        self.assertEqual(line["quantity"], 10.0)
        # El lote tiene stock(100) - consumo(0) = 100.
        self.assertEqual(line["stock_en_lote"], 100.0)

    # =========================================================================
    # CASO 8: DETALLE INCLUYE LÍMITE DE MERMA DEL PRODUCTO
    # =========================================================================
    def test_detalle_incluye_limite_de_merma(self):
        env = self._seed(stock=100.0, qty=10.0)
        env["product"].waste_limit = 8.0
        db.session.commit()

        # Merma 10 > límite 8 -> excede.
        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        line = data["lines"][0]
        self.assertEqual(line["waste_limit"], 8.0)
        self.assertTrue(line["excede_limite"])

        # Producto sin límite -> None y no excede (misma merma/pedido).
        env["product"].waste_limit = None
        db.session.commit()
        data2, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        line2 = data2["lines"][0]
        self.assertIsNone(line2["waste_limit"])
        self.assertFalse(line2["excede_limite"])


# =========================================================================
    # CASO 9: DECISIÓN MIXTA POR PRODUCTO -> APROBADO_PARCIAL + 1 notificación
    # =========================================================================
    def test_decision_mixta_por_producto(self):
        env = self._seed_multi(stock=100.0, qty_lote1=10.0, qty_lote2=5.0)

        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        lines = {l["lot_number"]: l for l in data["lines"]}
        lote_a = lines["L-AAA"]
        lote_b = lines["L-BBB"]
        self.assertEqual(len(data["lines"]), 2)

        reason = "Inspeccionamos y el lote está contaminado."
        res = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lote_a["detail_id"], "decision": "aprobar"},
            {"detail_id": lote_b["detail_id"], "decision": "rechazar", "reason": reason},
        ])
        self.assertTrue(res["success"], res)
        self.assertTrue(res["finalizado"])

        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "APROBADO_PARCIAL")

        # Stock: solo descontado el aprobado.
        db.session.refresh(env["inventory_a"])
        db.session.refresh(env["inventory_b"])
        self.assertEqual(float(env["inventory_a"].current_quantity), 90.0)
        self.assertEqual(float(env["inventory_b"].current_quantity), 100.0)

        # Una sola notificación final (mixta) que resume la merma completa.
        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_PARCIAL"
        ).all()
        self.assertEqual(len(notif), 1)
        self.assertIn("1 aprobado(s)", notif[0].message)
        self.assertIn("1 rechazado(s)", notif[0].message)

        # Auditoría con decisiones por línea y motivo del rechazo.
        audits = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).order_by(AuditLog.id.desc()).limit(2).all()
        final_log = audits[0]
        changed = json.loads(final_log.changed_data) if isinstance(final_log.changed_data, str) else final_log.changed_data
        self.assertEqual(changed.get("event"), "MERMA_PARCIAL")
        self.assertTrue(changed.get("finalizado"))
        self.assertEqual(len(changed["decisiones"]), 2)
        decisions = {x["decision"]: x for x in changed["decisiones"]}
        self.assertEqual(decisions["APROBADO"]["stock_antes"], 100.0)
        self.assertEqual(decisions["RECHAZADO"]["motivo"], reason)
        self.assertEqual(decisions["RECHAZADO"]["stock_antes"], None)
        # Cada línea guarda su foto y los productos normalizados llevan la decisión.
        self.assertIn("evidence_url", decisions["APROBADO"])
        self.assertIn("evidence_url", decisions["RECHAZADO"])
        prods = {p["producto"]: p for p in changed["productos"]}
        self.assertEqual(prods["Tomate"]["decision"], "APROBADO")
        self.assertEqual(prods["Cebolla"]["decision"], "RECHAZADO")
        self.assertEqual(prods["Cebolla"]["motivo"], reason)
        self.assertIn("motivo_rechazo", changed)

    # =========================================================================
    # CASO 10: DECISIÓN PARCIAL -> SALE DE LA CARGA, PERO LA MERMA SIGUE Y LA
    # NOTIFICACIÓN SE DIFERI HASTA DECIDIR LA ÚLTIMA LÍNEA
    # =========================================================================
    def test_decision_parcial_pendiente_y_notificacion_final(self):
        env = self._seed_multi(stock=100.0, qty_lote1=10.0, qty_lote2=5.0)

        data, error = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        self.assertIsNone(error)
        lines = {l["lot_number"]: l for l in data["lines"]}
        lote_a = lines["L-AAA"]
        lote_b = lines["L-BBB"]

        # Primera decisión: solo una línea aprobada -> cabecera sigue PENDIENTE.
        res_1 = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lote_a["detail_id"], "decision": "aprobar"},
        ])
        self.assertTrue(res_1["success"], res_1)
        self.assertFalse(res_1["finalizado"])

        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "PENDIENTE")
        db.session.refresh(env["inventory_a"])
        self.assertEqual(float(env["inventory_a"].current_quantity), 90.0)

        # Aún no hay notificación al autor (decisión incompleta).
        n_parcial = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_PARCIAL"
        ).all()
        self.assertEqual(n_parcial, [])
        audits = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).all()
        self.assertEqual(len(audits), 1)
        changed_1 = json.loads(audits[0].changed_data) if isinstance(audits[0].changed_data, str) else audits[0].changed_data
        self.assertEqual(changed_1.get("event"), "MERMA_DECISION")
        self.assertFalse(changed_1.get("finalizado"))

        # La merma sigue en la bandeja con el progreso reflejado.
        pend_book, _ = svc.get_pending_wastes_for_view(env["admin"].id)
        row = next(r for r in pend_book if r["id"] == env["waste"].id)
        self.assertEqual(row["lineas_decididas"], 1)
        self.assertEqual(row["lineas_total"], 2)

        # Segunda decisión (rechazo del otro lote) -> APROBADO_PARCIAL final.
        reason = "Producto en mal estado, se desecha."
        res_2 = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lote_b["detail_id"], "decision": "rechazar", "reason": reason},
        ])
        self.assertTrue(res_2["success"], res_2)
        self.assertTrue(res_2["finalizado"])

        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "APROBADO_PARCIAL")
        notif = Notification.query.filter_by(
            user_id=env["author"].id, type="MERMA_PARCIAL"
        ).all()
        self.assertEqual(len(notif), 1)

        # La merma ya no aparece en la bandeja de pendientes.
        pend_book, _ = svc.get_pending_wastes_for_view(env["admin"].id)
        self.assertTrue(all(r["id"] != env["waste"].id for r in pend_book))

    # =========================================================================
    # CASO 11: RECHAZO CON MOTIVO DEMASIADO CORTO -> error, sin cambios
    # =========================================================================
    def test_rechazo_sin_motivo_suficiente_no_toca_nada(self):
        env = self._seed_multi(stock=100.0, qty_lote1=10.0, qty_lote2=5.0)

        data, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        lines = {l["lot_number"]: l for l in data["lines"]}

        res = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lines["L-AAA"]["detail_id"], "decision": "aprobar"},
            {"detail_id": lines["L-BBB"]["detail_id"], "decision": "rechazar", "reason": "corto"},
        ])
        self.assertFalse(res["success"])
        self.assertIn("15 caracteres", res["message"])

        db.session.refresh(env["waste"])
        db.session.refresh(env["inventory_a"])
        db.session.refresh(env["inventory_b"])
        self.assertEqual(env["waste"].status, "PENDIENTE")
        self.assertEqual(float(env["inventory_a"].current_quantity), 100.0)
        self.assertEqual(float(env["inventory_b"].current_quantity), 100.0)
        self.assertEqual(AuditLog.query.filter_by(
            affected_table="waste", action="MERMA").count(), 0)

        # Las líneas siguen PENDIENTE con motivo vacío.
        detalle, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        after = {l["lot_number"]: l for l in detalle["lines"]}
        self.assertEqual(after["L-AAA"]["status"], "PENDIENTE")
        self.assertEqual(after["L-BBB"]["status"], "PENDIENTE")
        self.assertEqual(after["L-BBB"]["resolution_reason"], "")

    # =========================================================================
    # CASO 12: NI EL AUTOR NI UNA MERMA PROPIEDAD DEL ADMIN SE PUEDEN DECIDIR
    # =========================================================================
    def test_autor_no_puede_decidir(self):
        env = self._seed_multi()
        with self.assertRaises(PermissionError):
            svc.decidir_lineas(env["waste"].id, env["author"].id, [
                {"detail_id": 1, "decision": "aprobar"},
            ])
        db.session.rollback()

    def test_admin_no_puede_decidir_su_propia_merma(self):
        env = self._seed_multi()
        env["waste"].user_id = env["admin"].id
        db.session.commit()

        res = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": 1, "decision": "aprobar"},
        ])
        self.assertFalse(res["success"])
        self.assertIn("otro administrador", res["message"])

    # =========================================================================
    # CASO 13: CANCELAR UNA MERMA CON LÍNEA YA DECIDIDA -> bloqueado
    # =========================================================================
    def test_cancelar_parcial_decidida_bloqueado(self):
        env = self._seed_multi(stock=100.0, qty_lote1=10.0, qty_lote2=5.0)

        data, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        lote_a = data["lines"][0]
        first = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lote_a["detail_id"], "decision": "aprobar"},
        ])
        self.assertTrue(first["success"])
        self.assertFalse(first["finalizado"])

        res = svc.cancel_waste(env["waste"].id, env["author"].id, "Ya no la necesito")
        self.assertFalse(res["success"])
        self.assertIn("ya hay producto(s) decidido(s)", res["message"])
        db.session.refresh(env["waste"])
        self.assertEqual(env["waste"].status, "PENDIENTE")

    # =========================================================================
    # CASO 14: AUDITORÍA DE MERMAS -> la aprobada NO debe clasificarse como
    # rechazada y la mixta se muestra como APROBADO_PARCIAL con sus productos.
    # =========================================================================
    def test_audit_service_clasifica_parcial(self):
        env = self._seed_multi(stock=100.0, qty_lote1=10.0, qty_lote2=5.0)

        data, _ = svc.get_waste_detail(env["waste"].id, env["admin"].id)
        lote_a = data["lines"][0]
        lote_b = data["lines"][1]
        reason = "Lote en mal estado, se rechaza."
        res = svc.decidir_lineas(env["waste"].id, env["admin"].id, [
            {"detail_id": lote_a["detail_id"], "decision": "aprobar"},
            {"detail_id": lote_b["detail_id"], "decision": "rechazar", "reason": reason},
        ])
        self.assertTrue(res["success"])

        trail = WasteAuditService.get_formatted_audit_trail(env["admin"], {})
        self.assertEqual(len(trail), 1)
        entry = trail[0]
        self.assertEqual(entry["status"], "APROBADO_PARCIAL")
        prods = entry["changed_data"]["productos"]
        self.assertEqual(len(prods), 2)
        by_name = {p["producto"]: p for p in prods}
        self.assertEqual(by_name["Tomate"]["decision"], "APROBADO")
        self.assertEqual(by_name["Cebolla"]["decision"], "RECHAZADO")
        self.assertEqual(by_name["Cebolla"]["motivo"], reason)

    def test_audit_service_clasifica_aprobado_no_rechazado(self):
        # Regresión: una merma aprobada no debe quedar etiquetada como RECHAZADO.
        env = self._seed(stock=100.0, qty=10.0)
        res = svc.approve_waste(env["waste"].id, env["admin"].id)
        self.assertTrue(res["success"])

        trail = WasteAuditService.get_formatted_audit_trail(env["admin"], {})
        latest = trail[0]
        self.assertEqual(latest["status"], "APROBADO")


if __name__ == "__main__":
    unittest.main()
