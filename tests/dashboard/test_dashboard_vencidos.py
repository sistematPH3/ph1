# =============================================================================
# PRUEBAS DEL CUADRO DE VENCIDOS EN EL DASHBOARD
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) El cuadro solo aparece para OPERATIVE_ROLES
#   2) Cada usuario ve solo sus sedes asignadas
#   3) Admin ve todas las sedes
#   4) Contador correcto en la cabecera
#   5) El enlace de cada fila lleva product/lot/quantity correctos
#   6) Finance NO lo ve (aunque podría acceder a su ruta)
# =============================================================================

import os
import unittest
from datetime import date, timedelta

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
from app.models import (
    Inventory, Location, Movement, MovementDetail, Product, Role, User, WasteType,
)
from app.inventory.services.lot_availability_service import obtener_vencidos_para_dashboard


ROLE_IDS = {
    "Administrator": 1,
    "Operations": 2,
    "Manager": 3,
    "Management": 4,
    "Assistant Manager": 5,
    "Finance": 6,
}


class DashboardVencidosTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.session.execute(text('SET session_replication_role = replica'))
            for table in reversed(db.metadata.sorted_tables):
                try:
                    db.session.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
                except Exception:
                    pass
            db.session.execute(text('SET session_replication_role = DEFAULT'))
            db.session.commit()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
            except Exception:
                db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _seed_base(self, lot_expiration=None):
        """Crea: tipo VENCIDO, 3 sedes, producto, 3 usuarios (admin, ops, finance), inventario, traslados."""
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=30)

        waste_type = WasteType(
            name="Vencido", code="VENCIDO",
            severity="MEDIA", requires_approval=False,
            applies_central=False, is_active=True,
        )
        db.session.add(waste_type)
        db.session.flush()

        # Crear sedes: Central primero para que tome id=1
        loc_central = Location(name="Sede Central", state="Caracas")
        loc1 = Location(name="Sede Norte", state="Caracas")
        loc2 = Location(name="Sede Sur", state="Caracas")
        loc3 = Location(name="Sede Este", state="Caracas")
        db.session.add_all([loc_central, loc1, loc2, loc3])
        db.session.flush()
        
        assert loc_central.id == 1, f"Central debe tener id=1, tiene {loc_central.id}"

        product = Product(
            name="Tomate", sku=f"TOM-{waste_type.id}",
            unit_of_measure="kg", waste_limit=20.0, is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        role_admin = Role(id=ROLE_IDS["Administrator"], name="Administrator")
        role_ops = Role(id=ROLE_IDS["Operations"], name="Operations")
        role_fin = Role(id=ROLE_IDS["Finance"], name="Finance")
        db.session.add_all([role_admin, role_ops, role_fin])
        db.session.flush()

        user_admin = User(name="Admin", email="admin@test.com",
                          password_hash="x", role_id=role_admin.id)
        user_ops = User(name="Operador", email="ops@test.com",
                        password_hash="x", role_id=role_ops.id)
        user_fin = User(name="Finanzas", email="fin@test.com",
                        password_hash="x", role_id=role_fin.id)
        db.session.add_all([user_admin, user_ops, user_fin])
        db.session.flush()

        # Inventario en sedes operativas
        for loc in (loc1, loc2, loc3):
            inv = Inventory(
                location_id=loc.id, product_id=product.id,
                current_quantity=100.0, transit_quantity=0.0, min_stock=20.0,
            )
            db.session.add(inv)

        # Traslados COMPLETADOS con lotes vencidos
        for i, loc in enumerate((loc1, loc2, loc3), 1):
            mov = Movement(
                type="TRASLADO", origin_location_id=loc_central.id,
                destination_location_id=loc.id, status="COMPLETED", user_id=user_admin.id,
            )
            db.session.add(mov)
            db.session.flush()

            det = MovementDetail(
                movement_id=mov.id, product_id=product.id, lot_number=f"L-{i:03d}",
                quantity=10.0 * i, received_quantity=10.0 * i, missing_quantity=0.0,
                expiration_date=lot_expiration,
            )
            db.session.add(det)

        db.session.commit()

        return {
            "waste_type": waste_type,
            "loc1": loc1, "loc2": loc2, "loc3": loc3, "loc_central": loc_central,
            "product": product,
            "user_admin": user_admin, "user_ops": user_ops, "user_fin": user_fin,
        }

    # ------------------------------------------------------------------
    # 1) Cuadro solo para OPERATIVE_ROLES
    # ------------------------------------------------------------------
    def test_cuadro_solo_para_roles_operativos(self):
        env = self._seed_base()

        # Admin -> sí ve
        vencidos_admin = obtener_vencidos_para_dashboard(env["user_admin"])
        self.assertEqual(len(vencidos_admin), 3)

        # Operations -> sí ve (si tiene sedes asignadas)
        env["user_ops"].locations = [env["loc1"], env["loc2"]]
        db.session.commit()
        vencidos_ops = obtener_vencidos_para_dashboard(env["user_ops"])
        self.assertEqual(len(vencidos_ops), 2)

        # Finance -> NO ve (retorna lista vacía por is_finance)
        vencidos_fin = obtener_vencidos_para_dashboard(env["user_fin"])
        self.assertEqual(len(vencidos_fin), 0)

    # ------------------------------------------------------------------
    # 2) Cada usuario ve solo sus sedes asignadas
    # ------------------------------------------------------------------
    def test_usuario_ve_solo_sus_sedes_asignadas(self):
        env = self._seed_base()

        # Operador solo en loc1
        env["user_ops"].locations = [env["loc1"]]
        db.session.commit()

        vencidos = obtener_vencidos_para_dashboard(env["user_ops"])
        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0]["location_name"], "Sede Norte")
        self.assertEqual(vencidos[0]["lot_number"], "L-001")
        self.assertEqual(vencidos[0]["quantity"], 10.0)

        # Operador en loc1 y loc3
        env["user_ops"].locations = [env["loc1"], env["loc3"]]
        db.session.commit()

        vencidos = obtener_vencidos_para_dashboard(env["user_ops"])
        self.assertEqual(len(vencidos), 2)
        loc_names = {v["location_name"] for v in vencidos}
        self.assertIn("Sede Norte", loc_names)
        self.assertIn("Sede Este", loc_names)

    # ------------------------------------------------------------------
    # 3) Admin ve todas las sedes
    # ------------------------------------------------------------------
    def test_admin_ve_todas_las_sedes(self):
        env = self._seed_base()
        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        self.assertEqual(len(vencidos), 3)
        loc_names = {v["location_name"] for v in vencidos}
        self.assertEqual(loc_names, {"Sede Norte", "Sede Sur", "Sede Este"})

    # ------------------------------------------------------------------
    # 4) Contador correcto (cada lote = 1 fila)
    # ------------------------------------------------------------------
    def test_contador_correcto_por_lote(self):
        env = self._seed_base()
        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        # 3 sedes * 1 lote cada una = 3
        self.assertEqual(len(vencidos), 3)

        # Agregar segundo lote en loc1
        mov2 = Movement(
            type="TRASLADO", origin_location_id=env["loc_central"].id,
            destination_location_id=env["loc1"].id, status="COMPLETED",
            user_id=env["user_admin"].id,
        )
        db.session.add(mov2)
        db.session.flush()

        det2 = MovementDetail(
            movement_id=mov2.id, product_id=env["product"].id, lot_number="L-004",
            quantity=15.0, received_quantity=15.0, missing_quantity=0.0,
            expiration_date=date.today() - timedelta(days=5),
        )
        db.session.add(det2)
        db.session.commit()

        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        self.assertEqual(len(vencidos), 4)  # 3 + 1 extra

    # ------------------------------------------------------------------
    # 5) Enlace de cada fila lleva product/lot/quantity correctos
    # ------------------------------------------------------------------
    def test_enlace_fila_con_parametros_correctos(self):
        env = self._seed_base()
        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])

        for v in vencidos:
            # Verificar campos requeridos para el deep link
            self.assertIn("location_id", v)
            self.assertIn("product_id", v)
            self.assertIn("lot_number", v)
            self.assertIn("quantity", v)
            self.assertIn("expiration_date", v)
            self.assertIn("product_name", v)
            self.assertIn("location_name", v)

            # Tipos correctos
            self.assertIsInstance(v["location_id"], int)
            self.assertIsInstance(v["product_id"], int)
            self.assertIsInstance(v["lot_number"], str)
            self.assertIsInstance(v["quantity"], (int, float))
            self.assertIsInstance(v["expiration_date"], str)
            # Formato %d/%m/%Y
            parts = v["expiration_date"].split("/")
            self.assertEqual(len(parts), 3)
            day, month, year = map(int, parts)
            self.assertTrue(1 <= day <= 31)
            self.assertTrue(1 <= month <= 12)

    # ------------------------------------------------------------------
    # 6) Finance no lo ve (aunque acceda a su ruta)
    # ------------------------------------------------------------------
    def test_finance_no_ve_vencidos(self):
        env = self._seed_base()
        vencidos = obtener_vencidos_para_dashboard(env["user_fin"])
        self.assertEqual(vencidos, [])

        # Incluso si Finance tuviera sedes asignadas (no debería),
        # el servicio filtra por is_finance ANTES de revisar sedes
        env["user_fin"].locations = [env["loc1"]]
        db.session.commit()
        vencidos = obtener_vencidos_para_dashboard(env["user_fin"])
        self.assertEqual(vencidos, [])


if __name__ == "__main__":
    unittest.main()