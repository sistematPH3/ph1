# =============================================================================
# PRUEBA AUTOMÁTICA DE EDICIÓN DE MERMAS PENDIENTES (Modal + Página)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) GET  /api/waste/merma/<id>/edit (datos para el modal) -> Admin: OK.
#   2) Permisos por SEDE: un rol operativo con la sede asignada edita aunque
#      NO sea el autor (sin ventana de 24h). Sin sede -> 403.
#   3) POST /api/waste/merma/<id>/edit -> Admin actualiza y persiste
#      (total, motivo, costo según BD, auditoría MERMA_EDITADA).
#   4) Con el tipo VENCIDO solo se aceptan lotes REALMENTE vencidos; un lote
#      bueno -> 400.
#   5) La cantidad por lote no puede superar el saldo disponible del lote.
#   6) FOTOS: el modal envía evidence_urls por línea y evidence_url de cabecera;
#      se guardan como WasteDetailPhoto (con posición) y la cabecera se actualiza.
#   7) DECISIÓN PARCIAL: las líneas con decisión tomada (APROBADO/RECHAZADO) se
#      conservan intactas al editar (estado, lote, cantidad y fotos), se muestran
#      como solo-lectura en el GET, y el backend RECHAZA que el payload vuelva a
#      incluir un producto/lote ya decidido (400).
#
# Uso:
#   .venv/bin/python -m unittest tests.waste.test_waste_edit -v
# =============================================================================

import os
import unittest
import json
from datetime import datetime, timedelta

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
    Inventory, Location, Product, Purchase, PurchaseDetail,
    Movement, MovementDetail, Role, User,
    Waste, WasteDetail, WasteDetailPhoto, WasteType, AuditLog,
)


class WasteEditTest(unittest.TestCase):

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

    def _seed(self, sede_asignada=False):
        """Admin + rol operativo (Ops) + una merma PENDIENTE en Sede A.

        La rema la registra `author` (Operaciones). Solo el administrador puede
        editarla/cancelarla; los roles no-admin (Ops/Operations) quedan fuera.
        """
        role_admin = Role(name="Administrator")
        role_ops = Role(name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        admin = User(name="Admin", email="admin@edit.test",
                     password_hash="x", role_id=role_admin.id)
        ops = User(name="Operador", email="ops@edit.test",
                   password_hash="x", role_id=role_ops.id)
        author = User(name="Cocinera", email="cocina@edit.test",
                      password_hash="x", role_id=role_ops.id)
        loc_a = Location(name="Sede A", state="Caracas")
        loc_b = Location(name="Sede B", state="Caracas")
        product = Product(name="Tomate", sku="TOM-W1", unit_of_measure="kg")
        db.session.add_all([admin, ops, author, loc_a, loc_b, product])
        db.session.flush()

        if sede_asignada:
            ops.locations.append(loc_a)

        db.session.add(Inventory(
            location_id=loc_a.id, product_id=product.id,
            current_quantity=1000, transit_quantity=0.0, min_stock=20
        ))

        purchase = Purchase(invoice_url="factura-test.pdf", status="COMPLETED",
                            total_amount=100.0)
        db.session.add(purchase)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=purchase.id, product_id=product.id, lot_number="L-AAA",
            quantity=500, foreign_price=2.5, expiration_date=None
        ))

        wt = WasteType(name="Temperatura", code="TEMPERATURA",
                       requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc_a.id, waste_type_id=wt.id, user_id=author.id,
            status="PENDIENTE", total_quantity=10.0, notes="Merma de prueba",
            date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-AAA",
            expiration_date=None, quantity=10.0, unit_cost=2.5,
            subtotal_cost=25.0,
        ))
        db.session.commit()

        return {
            "admin": admin, "ops": ops, "author": author,
            "loc_a": loc_a, "loc_b": loc_b, "product": product,
            "waste": waste, "waste_type": wt,
        }

    def _seed_vencido(self):
        """Sede A + producto con dos lotes: uno vencido y otro 'bueno'."""
        role_admin = Role(name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin = User(name="Admin", email="admin@venc.test",
                     password_hash="x", role_id=role_admin.id)
        loc_a = Location(name="Sede A", state="Caracas")
        loc_b = Location(name="Sede B", state="Caracas")
        product = Product(name="Pescado", sku="PES-W1", unit_of_measure="kg")
        db.session.add_all([admin, loc_a, loc_b, product])
        db.session.flush()

        db.session.add(Inventory(
            location_id=loc_a.id, product_id=product.id,
            current_quantity=100, transit_quantity=0.0, min_stock=0
        ))

        mov = Movement(type="DESPACHO", origin_location_id=loc_b.id,
                       destination_location_id=loc_a.id, status="COMPLETED",
                       date=datetime.now())
        db.session.add(mov)
        db.session.flush()
        db.session.add_all([
            MovementDetail(movement_id=mov.id, product_id=product.id,
                           lot_number="L-EXP", quantity=100.0,
                           received_quantity=100.0, missing_quantity=0.0,
                           expiration_date=datetime.now().date() - timedelta(days=5)),
            MovementDetail(movement_id=mov.id, product_id=product.id,
                           lot_number="L-BUENO", quantity=100.0,
                           received_quantity=100.0, missing_quantity=0.0,
                           expiration_date=datetime.now().date() + timedelta(days=30)),
        ])

        wt = WasteType(name="Vencido", code="VENCIDO",
                       requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc_a.id, waste_type_id=wt.id, user_id=admin.id,
            status="PENDIENTE", total_quantity=5.0, notes="Vencido de prueba",
            date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-EXP",
            expiration_date=datetime.now().date() - timedelta(days=5),
            quantity=5.0, unit_cost=1.0, subtotal_cost=5.0,
        ))
        db.session.commit()

        return {"admin": admin, "loc_a": loc_a, "product": product,
                "waste": waste, "waste_type": wt}

    def _seed_con_decidida(self):
        """Merma PENDIENTE con 2 líneas: una PENDIENTE y una APROBADA.

        La línea aprobada simula una resolución parcial del admin: tiene
        estado, resolved_by/resolved_at, y una foto de evidencia. La cabecera
        también trae evidence_url (foto del ticket).
        """
        role_admin = Role(name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin = User(name="Admin", email="admin@decid.test",
                     password_hash="x", role_id=role_admin.id)
        loc_a = Location(name="Sede A", state="Caracas")
        product = Product(name="Tomate", sku="TOM-W1", unit_of_measure="kg")
        db.session.add_all([admin, loc_a, product])
        db.session.flush()

        db.session.add(Inventory(
            location_id=loc_a.id, product_id=product.id,
            current_quantity=1000, transit_quantity=0.0, min_stock=20
        ))

        purchase = Purchase(invoice_url="factura-test.pdf", status="COMPLETED",
                            total_amount=100.0)
        db.session.add(purchase)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=purchase.id, product_id=product.id, lot_number="L-AAA",
            quantity=500, foreign_price=2.5, expiration_date=None
        ))

        wt = WasteType(name="Temperatura", code="TEMPERATURA",
                       requires_approval=True, severity="MEDIA")
        db.session.add(wt)
        db.session.flush()

        waste = Waste(
            location_id=loc_a.id, waste_type_id=wt.id, user_id=admin.id,
            status="PENDIENTE", total_quantity=9.0, notes="Merma parcial",
            evidence_url="https://imgbb/header-original.jpg",
            date=datetime.now(),
        )
        db.session.add(waste)
        db.session.flush()

        pendiente = WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-AAA",
            expiration_date=None, quantity=4.0, unit_cost=2.5,
            subtotal_cost=10.0,
        )
        decided = WasteDetail(
            waste_id=waste.id, product_id=product.id, lot_number="L-DEC",
            expiration_date=None, quantity=5.0, unit_cost=2.5,
            subtotal_cost=12.5, status="APROBADO", resolved_by_id=admin.id,
            resolved_at=datetime.now(), resolution_reason="Revisado",
            evidence_url="https://imgbb/decidida-1.jpg",
        )
        db.session.add_all([pendiente, decided])
        db.session.flush()
        db.session.add(WasteDetailPhoto(
            waste_detail_id=decided.id, photo_url="https://imgbb/decidida-1.jpg",
            position=1
        ))
        db.session.commit()

        return {"admin": admin, "loc_a": loc_a, "product": product,
                "waste": waste, "waste_type": wt, "pendiente": pendiente,
                "decided": decided}

    # ------------------------------------------------------------------
    # CASO 1: GET datos para el modal -> Admin
    # ------------------------------------------------------------------
    def test_get_edit_admin_obtiene_datos(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.get("/api/waste/merma/{}/edit".format(env["waste"].id))
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        w = data["waste"]
        self.assertTrue(w["can_edit"])
        self.assertEqual(w["location_id"], env["loc_a"].id)
        self.assertEqual(w["waste_type_code"], "TEMPERATURA")
        self.assertFalse(w["is_vencido"])
        self.assertEqual(len(w["lines"]), 1)
        self.assertEqual(w["lines"][0]["product_id"], env["product"].id)

    # ------------------------------------------------------------------
    # CASO 2: Solo el ADMIN edita/cancela mermas (los roles no-admin quedan fuera)
    # ------------------------------------------------------------------
    def test_get_edit_ops_bloqueado(self):
        env = self._seed(sede_asignada=True)
        self._login(env["ops"].id)
        resp = self.client.get("/api/waste/merma/{}/edit".format(env["waste"].id))
        self.assertEqual(resp.status_code, 302)  # redirigido por require_roles

    def test_post_edit_ops_bloqueado(self):
        env = self._seed(sede_asignada=True)
        self._login(env["ops"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Intento sin permisos de admin",
                "lines": [{"product_id": env["product"].id,
                           "lot_number": "L-AAA", "quantity": 8}],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 302)  # redirigido por require_roles

    # ------------------------------------------------------------------
    # CASO 3: POST editar -> Admin actualiza y persiste
    # ------------------------------------------------------------------
    def test_post_edit_admin_actualiza(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Corregido a 8 kg",
                "lines": [{"product_id": env["product"].id,
                           "lot_number": "L-AAA", "quantity": 8}],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        waste = db.session.query(Waste).get(env["waste"].id)
        self.assertEqual(waste.status, "PENDIENTE")
        self.assertEqual(float(waste.total_quantity), 8.0)
        self.assertEqual(waste.notes, "Corregido a 8 kg")
        # Costo recalculado desde la BD (foreign_price 2.5 * 8)
        self.assertEqual(float(waste.total_cost), 20.0)

        audited = AuditLog.query.filter_by(affected_table="waste").all()
        self.assertTrue(any(
            (a.changed_data or {}).get("event") == "MERMA_EDITADA"
            for a in audited
        ))

    # ------------------------------------------------------------------
    # CASO 4: VENCIDO solo acepta lotes vencidos
    # ------------------------------------------------------------------
    def test_post_vencido_con_lote_bueno_rechazado(self):
        env = self._seed_vencido()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Intento con lote bueno",
                "lines": [{"product_id": env["product"].id,
                           "lot_number": "L-BUENO", "quantity": 6}],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("VENCIDO", data["message"].upper())

    def test_post_vencido_con_lote_vencido_aceptado(self):
        env = self._seed_vencido()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Ajustado a 6 kg",
                "lines": [{"product_id": env["product"].id,
                           "lot_number": "L-EXP", "quantity": 6}],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        waste = db.session.query(Waste).get(env["waste"].id)
        self.assertEqual(float(waste.total_quantity), 6.0)

    # ------------------------------------------------------------------
    # CASO 5: cantidad > saldo del lote -> rechazada
    # ------------------------------------------------------------------
    def test_post_edit_cantidad_excede_saldo_lote(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Exceso",
                "lines": [{"product_id": env["product"].id,
                           "lot_number": "L-AAA", "quantity": 9999}],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("supera", resp.get_json()["message"])

    # ------------------------------------------------------------------
    # CASO 6: FOTOS — evidence_urls por línea y evidence_url de cabecera
    # ------------------------------------------------------------------
    def test_post_guardar_fotos_por_linea_y_cabecera(self):
        env = self._seed()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Con fotos",
                "evidence_url": "https://imgbb/header-nueva.jpg",
                "lines": [{
                    "product_id": env["product"].id,
                    "lot_number": "L-AAA",
                    "quantity": 3,
                    "evidence_urls": ["https://imgbb/foto-1.jpg", "https://imgbb/foto-2.jpg"],
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        waste = db.session.query(Waste).get(env["waste"].id)
        self.assertEqual(waste.evidence_url, "https://imgbb/header-nueva.jpg")
        detail = waste.details[0]
        photos = sorted(
            WasteDetailPhoto.query.filter_by(waste_detail_id=detail.id).all(),
            key=lambda p: p.position
        )
        self.assertEqual([p.photo_url for p in photos],
                         ["https://imgbb/foto-1.jpg", "https://imgbb/foto-2.jpg"])
        self.assertEqual(photos[0].position, 1)
        self.assertEqual(photos[1].position, 2)
        # La primera foto también queda sincronizada en evidence_url de la línea
        self.assertEqual(detail.evidence_url, "https://imgbb/foto-1.jpg")

    def test_post_quitar_fotos_y_cabecera(self):
        env = self._seed()
        self._login(env["admin"].id)
        first = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Con fotos",
                "evidence_url": "https://imgbb/header-1.jpg",
                "lines": [{
                    "product_id": env["product"].id,
                    "lot_number": "L-AAA",
                    "quantity": 3,
                    "evidence_urls": ["https://imgbb/foto-1.jpg"],
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)

        # Segunda edición sin fotos ni evidencia de cabecera -> se limpian
        second = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Sin fotos",
                "evidence_url": None,
                "lines": [{
                    "product_id": env["product"].id,
                    "lot_number": "L-AAA",
                    "quantity": 3,
                    "evidence_urls": [],
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 200)

        waste = db.session.query(Waste).get(env["waste"].id)
        self.assertIsNone(waste.evidence_url)
        detail = waste.details[0]
        self.assertEqual(
            WasteDetailPhoto.query.filter_by(waste_detail_id=detail.id).count(), 0
        )
        self.assertIsNone(detail.evidence_url)

    # ------------------------------------------------------------------
    # CASO 7: DECISIÓN PARCIAL — líneas decididas se preservan y bloquean
    # ------------------------------------------------------------------
    def test_get_marca_decidida_no_editable(self):
        env = self._seed_con_decidida()
        self._login(env["admin"].id)
        resp = self.client.get("/api/waste/merma/{}/edit".format(env["waste"].id))
        self.assertEqual(resp.status_code, 200)
        lines = {str(l["lot_number"]): l for l in resp.get_json()["waste"]["lines"]}

        dec = lines["L-DEC"]
        self.assertEqual(dec["status"], "APROBADO")
        self.assertTrue(dec["decided"])
        self.assertFalse(dec["editable"])
        self.assertEqual(dec["photos"], ["https://imgbb/decidida-1.jpg"])

        pend = lines["L-AAA"]
        self.assertEqual(pend["status"], "PENDIENTE")
        self.assertFalse(pend["decided"])
        self.assertTrue(pend["editable"])

    def test_post_editar_preserva_linea_decidida(self):
        env = self._seed_con_decidida()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Ajusto solo la pendiente",
                "lines": [{
                    "product_id": env["product"].id,
                    "lot_number": "L-AAA",
                    "quantity": 3,
                    "evidence_urls": ["https://imgbb/pendiente-nueva.jpg"],
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])

        waste = db.session.query(Waste).get(env["waste"].id)
        # La línea decidida sigue INTACTA
        decided = next(d for d in waste.details if d.lot_number == "L-DEC")
        self.assertEqual(decided.status, "APROBADO")
        self.assertEqual(float(decided.quantity), 5.0)
        self.assertEqual(decided.resolution_reason, "Revisado")
        self.assertEqual(decided.resolved_by_id, env["admin"].id)
        self.assertEqual(
            [p.photo_url for p in decided.photos], ["https://imgbb/decidida-1.jpg"]
        )
        # Las decididas ya descontaron stock: el total = decidida + nueva pendiente
        self.assertEqual(float(waste.total_quantity), 8.0)  # 5 decidida + 3 pendiente

        pendiente = next(d for d in waste.details if d.lot_number == "L-AAA")
        self.assertEqual(float(pendiente.quantity), 3.0)
        self.assertEqual(
            [p.photo_url for p in pendiente.photos], ["https://imgbb/pendiente-nueva.jpg"]
        )

    def test_post_rechaza_reelegir_linea_decidida(self):
        env = self._seed_con_decidida()
        self._login(env["admin"].id)
        resp = self.client.post(
            "/api/waste/merma/{}/edit".format(env["waste"].id),
            data=json.dumps({
                "waste_type_id": env["waste_type"].id,
                "notes": "Intento tocar la decidida",
                "lines": [{
                    "product_id": env["product"].id,
                    "lot_number": "L-DEC",
                    "quantity": 4,
                    "evidence_urls": [],
                }],
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("decisión", data["message"].lower())

        waste = db.session.query(Waste).get(env["waste"].id)
        decided = next(d for d in waste.details if d.lot_number == "L-DEC")
        self.assertEqual(decided.status, "APROBADO")
        self.assertEqual(float(decided.quantity), 5.0)


if __name__ == "__main__":
    unittest.main()