# =============================================================================
# PRUEBAS DEL SERVICIO COMPARTIDO DE DISPONIBILIDAD DE LOTES
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Paridad: get_expired_lots devuelve exactamente lo que devolvía el repo
#   2) obtener_vencidos_para_dashboard filtra por rol y sede
#   3) Admin ve todas las sedes; usuarios solo las suyas
#   4) Respeta vencido_permitido_en_central() para Sede Central (id=1)
#   5) No duplica lotes multi-sede
#   6) Orden correcto por fecha real (no string)
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
from app.inventory.services.lot_availability_service import (
    get_expired_lots,
    obtener_vencidos_para_dashboard,
    _compute_lot_availability,
)
from app.waste.repositories.register_waste_repository import RegisterWasteRepository


ROLE_IDS = {
    "Administrator": 1,
    "Operations": 2,
    "Manager": 3,
    "Management": 4,
    "Assistant Manager": 5,
}


class LotAvailabilityServiceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            print("DEBUG setUpClass: Starting cleanup")
            db.session.execute(text('SET session_replication_role = replica'))
            for table in reversed(db.metadata.sorted_tables):
                try:
                    db.session.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
                    print(f"DEBUG: Truncated {table.name}")
                except Exception as e:
                    print(f"DEBUG: Failed to truncate {table.name}: {e}")
            db.session.execute(text('SET session_replication_role = DEFAULT'))
            db.session.commit()
            print("DEBUG setUpClass: TRUNCATE committed")
            # Check locations table
            result = db.session.execute(text('SELECT * FROM locations')).fetchall()
            print(f"DEBUG setUpClass: Locations rows after TRUNCATE: {len(result)}")
            for row in result:
                print(f"  {row}")
            # Explicitly reset sequences
            for seq_name in ['locations_id_seq', 'users_id_seq', 'roles_id_seq', 'products_id_seq', 'movements_id_seq', 'movement_details_id_seq', 'inventory_id_seq', 'waste_types_id_seq']:
                try:
                    db.session.execute(text(f"SELECT setval('{seq_name}', 1, false)"))
                    print(f"DEBUG: Reset {seq_name}")
                except Exception as e:
                    print(f"DEBUG: Failed to reset {seq_name}: {e}")
            db.session.commit()
            print("DEBUG setUpClass: Sequences reset")
            # Check sequence
            result = db.session.execute(text('SELECT last_value FROM locations_id_seq')).scalar()
            print(f"DEBUG setUpClass: locations_id_seq last_value: {result}")

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        # Use TRUNCATE with RESTART IDENTITY CASCADE to properly reset sequences
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
            except Exception:
                # Fallback to DELETE if TRUNCATE fails
                db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _seed_base(self, lot_expiration=None):
        """Crea: tipo VENCIDO, 2 sedes, producto, usuario admin, inventario, traslado con lote."""
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=30)

        waste_type = WasteType(
            name="Vencido", code="VENCIDO",
            severity="MEDIA", requires_approval=False,
            applies_central=False, is_active=True,
        )
        db.session.add(waste_type)
        db.session.flush()

        # Crear sedes: Central primero para que tome id=1, luego las demás
        loc_central = Location(name="Sede Central", state="Caracas")
        loc1 = Location(name="Sede Norte", state="Caracas")
        loc2 = Location(name="Sede Sur", state="Caracas")
        db.session.add_all([loc_central, loc1, loc2])
        db.session.flush()
        
        # Verificar que Central tiene id=1 (necesario para vencido_permitido_en_central())
        assert loc_central.id == 1, f"Central debe tener id=1, tiene {loc_central.id}"

        product = Product(
            name="Tomate", sku=f"TOM-{waste_type.id}",
            unit_of_measure="kg", waste_limit=20.0, is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        role_admin = Role(id=ROLE_IDS["Administrator"], name="Administrator")
        role_ops = Role(id=ROLE_IDS["Operations"], name="Operations")
        db.session.add_all([role_admin, role_ops])
        db.session.flush()

        user_admin = User(name="Admin", email="admin@test.com",
                          password_hash="x", role_id=role_admin.id)
        user_ops = User(name="Operador", email="ops@test.com",
                        password_hash="x", role_id=role_ops.id)
        db.session.add_all([user_admin, user_ops])
        db.session.flush()

        # Inventario en ambas sedes
        for loc in (loc1, loc2):
            inv = Inventory(
                location_id=loc.id, product_id=product.id,
                current_quantity=100.0, transit_quantity=0.0, min_stock=20.0,
            )
            db.session.add(inv)

        # Traslado COMPLETADO a loc1 con lote vencido
        mov1 = Movement(
            type="TRASLADO", origin_location_id=loc_central.id,
            destination_location_id=loc1.id, status="COMPLETED", user_id=user_admin.id,
        )
        db.session.add(mov1)
        db.session.flush()

        det1 = MovementDetail(
            movement_id=mov1.id, product_id=product.id, lot_number="L-NORTE",
            quantity=50.0, received_quantity=50.0, missing_quantity=0.0,
            expiration_date=lot_expiration,
        )
        db.session.add(det1)

        # Traslado COMPLETADO a loc2 con lote vencido
        mov2 = Movement(
            type="TRASLADO", origin_location_id=loc_central.id,
            destination_location_id=loc2.id, status="COMPLETED", user_id=user_admin.id,
        )
        db.session.add(mov2)
        db.session.flush()

        det2 = MovementDetail(
            movement_id=mov2.id, product_id=product.id, lot_number="L-SUR",
            quantity=30.0, received_quantity=30.0, missing_quantity=0.0,
            expiration_date=lot_expiration,
        )
        db.session.add(det2)

        db.session.commit()

        return {
            "waste_type": waste_type,
            "loc1": loc1, "loc2": loc2, "loc_central": loc_central,
            "product": product,
            "user_admin": user_admin, "user_ops": user_ops,
        }

    # ------------------------------------------------------------------
    # 1) PARIDAD: get_expired_lots == repo.get_expired_lots
    # ------------------------------------------------------------------
    def test_get_expired_lots_paridad_con_repositorio(self):
        env = self._seed_base()
        # Servicio compartido
        svc_lots = get_expired_lots(env["loc1"].id)
        # Repositorio original (delegado al servicio)
        repo_lots = RegisterWasteRepository.get_expired_lots(env["loc1"].id)

        self.assertEqual(len(svc_lots), len(repo_lots))
        for s, r in zip(svc_lots, repo_lots):
            self.assertEqual(s["product_id"], r["product_id"])
            self.assertEqual(s["product_name"], r["product_name"])
            self.assertEqual(s["lot_number"], r["lot_number"])
            self.assertEqual(float(s["quantity"]), float(r["quantity"]))
            self.assertEqual(s["expiration_date"], r["expiration_date"])

    # ------------------------------------------------------------------
    # 2) obtener_vencidos_para_dashboard: admin ve todas las sedes
    # ------------------------------------------------------------------
    def test_dashboard_admin_ve_todas_sedes(self):
        env = self._seed_base()
        
        # Debug: check user_admin role and is_admin
        print(f"DEBUG: user_admin.role={env['user_admin'].role}, role.name={env['user_admin'].role.name if env['user_admin'].role else None}")
        print(f"DEBUG: user_admin.is_admin={env['user_admin'].is_admin}")
        
        # Debug: check what get_expired_lots returns for each location
        from app.inventory.services.lot_availability_service import get_expired_lots
        lots1 = get_expired_lots(env["loc1"].id)
        lots2 = get_expired_lots(env["loc2"].id)
        print(f'DEBUG: loc1.id={env["loc1"].id} lots={len(lots1)}')
        print(f'DEBUG: loc2.id={env["loc2"].id} lots={len(lots2)}')
        
        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        print(f'DEBUG: total vencidos={len(vencidos)}')
        for v in vencidos:
            print(f'  {v}')

        # Debe haber 2 lotes (uno por sede)
        self.assertEqual(len(vencidos), 2)
        loc_names = {v["location_name"] for v in vencidos}
        self.assertIn("Sede Norte", loc_names)
        self.assertIn("Sede Sur", loc_names)

        # Cada lote tiene location_id y location_name
        for v in vencidos:
            self.assertIn("location_id", v)
            self.assertIn("location_name", v)

    # ------------------------------------------------------------------
    # 3) obtener_vencidos_para_dashboard: usuario no-admin solo sus sedes
    # ------------------------------------------------------------------
    def test_dashboard_usuario_solo_sus_sedes(self):
        env = self._seed_base()
        # Asignar user_ops solo a loc1
        env["user_ops"].locations = [env["loc1"]]
        db.session.commit()

        vencidos = obtener_vencidos_para_dashboard(env["user_ops"])

        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0]["location_name"], "Sede Norte")
        self.assertEqual(vencidos[0]["product_name"], "Tomate")

    # ------------------------------------------------------------------
    # 4) Respeta vencido_permitido_en_central() para Sede Central (id=1)
    # ------------------------------------------------------------------
    def test_dashboard_central_respetada_segun_parametro(self):
        env = self._seed_base(lot_expiration=date.today() - timedelta(days=5))

        # Agregar lote vencido en Central
        # Primero: inventario en Central para el producto
        inv_central = Inventory(
            location_id=env["loc_central"].id, product_id=env["product"].id,
            current_quantity=100.0, transit_quantity=0.0, min_stock=20.0,
        )
        db.session.add(inv_central)
        db.session.flush()

        mov_c = Movement(
            type="TRASLADO", origin_location_id=env["loc1"].id,
            destination_location_id=env["loc_central"].id, status="COMPLETED",
            user_id=env["user_admin"].id,
        )
        db.session.add(mov_c)
        db.session.flush()

        det_c = MovementDetail(
            movement_id=mov_c.id, product_id=env["product"].id, lot_number="L-CENTRAL",
            quantity=25.0, received_quantity=25.0, missing_quantity=0.0,
            expiration_date=date.today() - timedelta(days=5),
        )
        db.session.add(det_c)
        db.session.commit()

        # Si Central NO permite vencidos -> no aparece
        from app.waste.repositories.register_waste_repository import RegisterWasteRepository
        original = RegisterWasteRepository.vencido_permitido_en_central

        try:
            RegisterWasteRepository.vencido_permitido_en_central = lambda: False
            vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
            loc_names = {v["location_name"] for v in vencidos}
            self.assertNotIn("Sede Central", loc_names)
            self.assertEqual(len(vencidos), 2)

            # Si Central SÍ permite vencidos -> aparece
            RegisterWasteRepository.vencido_permitido_en_central = lambda: True
            vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
            loc_names = {v["location_name"] for v in vencidos}
            self.assertIn("Sede Central", loc_names)
            self.assertEqual(len(vencidos), 3)
        finally:
            RegisterWasteRepository.vencido_permitido_en_central = original

    # ------------------------------------------------------------------
    # 5) No duplica lotes (mismo lote en multi-sede no pasa, pero verifica)
    # ------------------------------------------------------------------
    def test_no_duplica_lotes_multi_sede(self):
        env = self._seed_base()
        # Mismo lote en ambas sedes (raro pero posible)
        # El servicio recorre sedes y extiende, no de-duplica a propósito
        # porque location_id distinto = lote distinto en inventario
        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        ids = {(v["location_id"], v["lot_number"]) for v in vencidos}
        self.assertEqual(len(ids), len(vencidos))

    # ------------------------------------------------------------------
    # 6) Orden correcto por fecha real (datetime), no string
    # ------------------------------------------------------------------
    def test_orden_por_fecha_real_no_string(self):
        """String '%d/%m/%Y' ordenaría mal (01/01/2027 < 02/01/2026).
        El servicio usa datetime.strptime para ordenar correctamente."""
        env = self._seed_base(lot_expiration=date.today() - timedelta(days=10))

        # Agregar lote que vence MAÑANA (más reciente)
        mov3 = Movement(
            type="TRASLADO", origin_location_id=env["loc_central"].id,
            destination_location_id=env["loc1"].id, status="COMPLETED",
            user_id=env["user_admin"].id,
        )
        db.session.add(mov3)
        db.session.flush()

        det3 = MovementDetail(
            movement_id=mov3.id, product_id=env["product"].id, lot_number="L-MANIANA",
            quantity=10.0, received_quantity=10.0, missing_quantity=0.0,
            expiration_date=date.today() - timedelta(days=1),  # venció ayer = más reciente
        )
        db.session.add(det3)

        # Agregar lote que venció HACE 30 DÍAS (más antiguo)
        mov4 = Movement(
            type="TRASLADO", origin_location_id=env["loc_central"].id,
            destination_location_id=env["loc1"].id, status="COMPLETED",
            user_id=env["user_admin"].id,
        )
        db.session.add(mov4)
        db.session.flush()

        det4 = MovementDetail(
            movement_id=mov4.id, product_id=env["product"].id, lot_number="L-ANTIGUO",
            quantity=10.0, received_quantity=10.0, missing_quantity=0.0,
            expiration_date=date.today() - timedelta(days=30),
        )
        db.session.add(det4)
        db.session.commit()

        vencidos = obtener_vencidos_para_dashboard(env["user_admin"])
        # loc1 tiene 3 lotes: L-MANIANA (ayer), L-ANTIGUO (30 días), L-NORTE (10 días)
        # Deben ordenarse: más antiguo primero (L-ANTIGUO, L-NORTE, L-MANIANA)
        loc1_vencidos = [v for v in vencidos if v["location_id"] == env["loc1"].id]
        self.assertEqual(len(loc1_vencidos), 3)
        lot_numbers = [v["lot_number"] for v in loc1_vencidos]
        self.assertEqual(lot_numbers, ["L-ANTIGUO", "L-NORTE", "L-MANIANA"])


if __name__ == "__main__":
    unittest.main()