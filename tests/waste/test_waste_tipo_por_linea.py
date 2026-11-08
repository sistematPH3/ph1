"""
Motivo de merma POR PRODUCTO (waste_details.waste_type_id).

Qué verifica:
  1) Registro: dos productos en el mismo ticket con MOTIVOS DISTINTOS; cada
     línea guarda su PROPIO waste_type_id (obligatorio por producto). La merma
     queda PENDIENTE porque UN producto trae un tipo que exige aprobación, y la
     novedad TIPO se marca SOLO para ese producto.
  2) Edición (GET): el expediente expone por línea el tipo efectivo, su nombre
     y si la cantidad supera el límite de merma del producto (excede_limite).
  3) Edición (POST): cambiar el motivo de UNA línea la persiste en su detalle
     sin tocar el tipo de las demás.
  4) Resolución (GET): cada línea informa su propio waste_type_name.

Uso:
  .venv/bin/python -m unittest tests.waste.test_waste_tipo_por_linea -v
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
    AuditLog, Inventory, Location, Movement, MovementDetail, Product, Role, User,
    Waste, WasteType, WasteDetail,
)
from app.waste.services.register_waste_service import register_waste  # noqa: E402
from app.waste.services.waste_approvals_service import get_waste_detail  # noqa: E402
from app.waste.services.waste_edit_service import WasteEditService  # noqa: E402
from app.waste.services.waste_audit_service import WasteAuditService  # noqa: E402


class MotivoPorLineaTest(unittest.TestCase):

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
        role_admin = Role(id=1, name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin1 = User(name="Admin Uno", email="autor@motivo.test",
                      password_hash="x", role_id=role_admin.id)
        admin2 = User(name="Admin Dos", email="resuelve@motivo.test",
                      password_hash="x", role_id=role_admin.id)
        central = Location(name="Sede Central", state="Caracas")
        sede_a = Location(name="Sede A", state="Caracas")
        db.session.add_all([admin1, admin2, central, sede_a])
        db.session.flush()

        p1 = Product(name="Tomate", sku="TOM-M1", unit_of_measure="kg",
                     waste_limit=5.0, is_active=True)
        p2 = Product(name="Pescado", sku="PES-M1", unit_of_measure="kg",
                     is_active=True)
        db.session.add_all([p1, p2])
        db.session.flush()

        for i, p in enumerate([p1, p2]):
            db.session.add(Inventory(
                location_id=sede_a.id, product_id=p.id,
                current_quantity=100.0, transit_quantity=0.0,
                min_stock=20.0,
            ))
            mov = Movement(
                type="TRASLADO", origin_location_id=central.id,
                destination_location_id=sede_a.id, status="COMPLETED",
                user_id=admin1.id, date=datetime.now(),
            )
            db.session.add(mov)
            db.session.flush()
            lot = f"L-00{i + 1}"
            db.session.add(MovementDetail(
                movement_id=mov.id, product_id=p.id, lot_number=lot,
                quantity=100.0, received_quantity=100.0,
                missing_quantity=0.00, expiration_date=None,
            ))

        base = WasteType(name="Operación", code="OPERACION",
                         requires_approval=False, severity="MEDIA",
                         is_active=True)
        temp = WasteType(name="Temperatura", code="TEMPERATURA",
                         requires_approval=True, severity="ALTA",
                         is_active=True)
        dano = WasteType(name="Dañado", code="DANADO",
                         requires_approval=False, severity="MEDIA",
                         is_active=True)
        db.session.add_all([base, temp, dano])
        db.session.flush()
        db.session.commit()

        return {
            "admin1": admin1, "admin2": admin2, "sede_a": sede_a,
            "p1": p1, "p2": p2,
            "base": base, "temp": temp, "dano": dano,
        }

    def _register_both(self, env, temp_on_first=True):
        return register_waste(
            user_id=env["admin1"].id,
            location_id=env["sede_a"].id,
            items=[
                {
                    "product_id": env["p1"].id,
                    "lot_number": "L-001",
                    "quantity": 8.0,
                    "waste_type_id": env["temp"].id if temp_on_first else env["base"].id,
                },
                {
                    "product_id": env["p2"].id,
                    "lot_number": "L-002",
                    "quantity": 3.0,
                    "waste_type_id": env["base"].id,
                },
            ],
            evidence_url=None,
            notes="Merma con motivos distintos por producto",
            request_id="LIN-01",
        )

    # ------------------------------------------------------------------
    def test_registro_motivos_distintos_por_producto(self):
        env = self._seed()
        res = self._register_both(env)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")

        waste = Waste.query.get(res["waste_id"])
        details_by_pid = {d.product_id: d for d in waste.details}
        # La línea 1 trae su propio tipo (TEMPERATURA), la 2 también (OPERACIÓN).
        self.assertEqual(details_by_pid[env["p1"].id].waste_type_id, env["temp"].id)
        self.assertEqual(details_by_pid[env["p2"].id].waste_type_id, env["base"].id)
        # El tipo del TICKET se deriva de la primera línea (TEMPERATURA).
        self.assertEqual(waste.waste_type_id, env["temp"].id)

        # La novedad TIPO se marca SOLO para el producto con el tipo que exige
        # aprobación (TEMPERATURA), no para el que heredó OPERACIÓN.
        nov = res["novedades"]
        self.assertIn("TIPO", nov[str(env["p1"].id)]["motivos"])
        p2_motivos = nov.get(str(env["p2"].id), {}).get("motivos", [])
        self.assertNotIn("TIPO", p2_motivos)

    def test_get_edit_expone_tipo_y_limite_por_linea(self):
        env = self._seed()
        res = self._register_both(env)

        data, error = WasteEditService.get_waste_for_edit(
            res["waste_id"], env["admin1"].id, True,
        )
        self.assertIsNone(error)
        lines_by_pid = {l["product_id"]: l for l in data["lines"]}
        # p1: cantidad 8 supera su límite 5 -> excede_limite True + tipo TEMPERATURA.
        l1 = lines_by_pid[env["p1"].id]
        self.assertEqual(l1["waste_type_id"], env["temp"].id)
        self.assertEqual(l1["waste_type_name"], "Temperatura")
        self.assertEqual(l1["waste_limit"], 5.0)
        self.assertTrue(l1["excede_limite"])
        # p2: motivo propio OPERACIÓN, sin límite configurado.
        l2 = lines_by_pid[env["p2"].id]
        self.assertEqual(l2["waste_type_id"], env["base"].id)
        self.assertEqual(l2["waste_type_name"], "Operación")
        self.assertIsNone(l2["waste_limit"])
        # El expediente ofrece la lista completa de tipos para el selector.
        ids = {t["id"] for t in data["waste_types"]}
        self.assertTrue({env["base"].id, env["temp"].id, env["dano"].id} <= ids)

    def test_editar_cambia_motivo_de_una_linea_solo(self):
        env = self._seed()
        res = self._register_both(env)

        detail = next(
            d for d in Waste.query.get(res["waste_id"]).details
            if d.product_id == env["p1"].id
        )
        # Cambiar SOLO el motivo de la línea 1 a DANADO (y subir cantidad).
        payload = {
            "waste_type_id": env["base"].id,
            "notes": "Corrección del motivo de la línea 1",
            "lines": [
                {
                    "product_id": env["p1"].id,
                    "lot_number": "L-001",
                    "quantity": 6.0,
                    "waste_type_id": env["dano"].id,
                    "expiration_date": None,
                },
                {
                    "product_id": env["p2"].id,
                    "lot_number": "L-002",
                    "quantity": 3.0,
                    "expiration_date": None,
                },
            ],
        }
        ok, status = WasteEditService.edit_pending_waste(
            res["waste_id"], payload, env["admin1"].id, True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(ok["success"])

        waste = Waste.query.get(res["waste_id"])
        details_by_pid = {d.product_id: d for d in waste.details}
        self.assertEqual(details_by_pid[env["p1"].id].waste_type_id, env["dano"].id)
        # La línea 2 quedó intacta, con su motivo OPERACIÓN.
        self.assertEqual(details_by_pid[env["p2"].id].waste_type_id, env["base"].id)
        # El tipo del TICKET se re-deriva de la primera línea (ahora DANADO).
        self.assertEqual(waste.waste_type_id, env["dano"].id)

        # Resolver (GET) ahora muestra el nuevo motivo por línea.
        detail_data, error = get_waste_detail(res["waste_id"], env["admin2"].id)
        self.assertIsNone(error)
        dl_by_pid = {l["product_id"]: l for l in detail_data["lines"]}
        self.assertEqual(dl_by_pid[env["p1"].id]["waste_type_name"], "Dañado")
        self.assertEqual(dl_by_pid[env["p2"].id]["waste_type_name"], "Operación")

    def test_resolver_muestra_motivo_por_linea(self):
        env = self._seed()
        res = self._register_both(env)

        data, error = get_waste_detail(res["waste_id"], env["admin2"].id)
        self.assertIsNone(error)
        for d in data["lines"]:
            if d["product_id"] == env["p1"].id:
                self.assertEqual(d["waste_type_name"], "Temperatura")
                self.assertTrue(d["excede_limite"])
            else:
                self.assertEqual(d["waste_type_name"], "Operación")
                self.assertFalse(d["excede_limite"])

    def test_edit_registra_auditoria_con_cantidades_y_motivo_por_linea(self):
        env = self._seed()
        res = self._register_both(env)

        payload = {
            "waste_type_id": env["base"].id,
            "notes": "Nota de auditoría de edición",
            "lines": [
                {
                    "product_id": env["p1"].id,
                    "lot_number": "L-001",
                    "quantity": 6.0,
                    "waste_type_id": env["dano"].id,
                    "expiration_date": None,
                },
                {
                    "product_id": env["p2"].id,
                    "lot_number": "L-002",
                    "quantity": 3.0,
                    "expiration_date": None,
                },
            ],
        }
        ok, status = WasteEditService.edit_pending_waste(
            res["waste_id"], payload, env["admin1"].id, True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(ok["success"])

        # Log de auditoría de mermas con el detalle para conservar el motivo.
        log = (
            AuditLog.query
            .filter(AuditLog.action == "MERMA")
            .order_by(AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(log)
        cd = log.changed_data
        self.assertEqual(cd.get("event"), "MERMA_EDITADA")
        self.assertEqual(cd.get("cantidad_antes"), 11.0)
        self.assertEqual(cd.get("cantidad_despues"), 9.0)
        self.assertEqual(cd.get("motivo_edicion"), "Nota de auditoría de edición")

        after = {l["product_id"]: l for l in cd["after"]["lines"]}
        self.assertEqual(after[env["p1"].id]["waste_type_id"], env["dano"].id)
        self.assertEqual(after[env["p2"].id]["waste_type_id"], env["base"].id)
        before = {l["product_id"]: l for l in cd["before"]["lines"]}
        self.assertEqual(before[env["p1"].id]["waste_type_id"], env["temp"].id)
        self.assertEqual(before[env["p2"].id]["waste_type_id"], env["base"].id)

        # La auditoría de mermas expone por línea su propio motivo_tipo.
        trails = WasteAuditService.get_formatted_audit_trail(env["admin2"], {})
        edit_trail = next(
            (t for t in trails if t["changed_data"].get("event") == "MERMA_EDITADA"),
            None,
        )
        self.assertIsNotNone(edit_trail)
        pros = {p["producto"]: p for p in edit_trail["changed_data"]["productos"]}
        self.assertEqual(pros["Tomate"]["motivo_tipo"], "Dañado")
        self.assertEqual(pros["Tomate"]["cantidad"], 6.0)
        self.assertEqual(pros["Pescado"]["motivo_tipo"], "Operación")
        self.assertEqual(pros["Pescado"]["cantidad"], 3.0)

    def test_editar_no_permite_agregar_producto_nuevo(self):
        env = self._seed()
        # Merma con UN solo producto (Pollo).
        res = self._register_uno(env)

        payload = {
            "waste_type_id": env["base"].id,
            "notes": "Intento de agregar otro producto",
            "lines": [
                {
                    "product_id": env["p1"].id,
                    "lot_number": "L-001",
                    "quantity": 3.0,
                    "expiration_date": None,
                },
                # Producto NUEVO que no estaba en la merma original.
                {
                    "product_id": env["p2"].id,
                    "lot_number": "L-002",
                    "quantity": 2.0,
                    "expiration_date": None,
                },
            ],
        }
        ok, status = WasteEditService.edit_pending_waste(
            res["waste_id"], payload, env["admin1"].id, True,
        )
        self.assertEqual(status, 400)
        self.assertFalse(ok["success"])
        self.assertIn("agregar el producto", ok["message"])

        # La merma siguió igual: no quedó el producto nuevo.
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(len(waste.details), 1)
        self.assertEqual(waste.details[0].product_id, env["p1"].id)

    def _register_uno(self, env):
        return register_waste(
            user_id=env["admin1"].id,
            location_id=env["sede_a"].id,
            items=[
                {
                    "product_id": env["p1"].id,
                    "lot_number": "L-001",
                    "quantity": 3.0,
                    "waste_type_id": env["temp"].id,
                },
            ],
            evidence_url=None,
            notes="Merma de un producto",
            request_id="LIN-ONE",
        )


if __name__ == "__main__":
    unittest.main()