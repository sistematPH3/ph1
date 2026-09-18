# =============================================================================
# PRUEBAS DE APROBACIÓN POR LÍMITE DESDE LA ALARMA DE VENCIDOS
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Merma VENCIDO que NO supera waste_limit → entra APROBADA (directa)
#   2) Merma VENCIDO que SÍ supera waste_limit → entra PENDIENTE y notifica al admin
#   3) El flujo es el normal verificado desde la alarma (deep link)
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
    Inventory, Location, Movement, MovementDetail, Product, Role, User, WasteType, Waste, Notification,
)
from app.waste.services.register_waste_service import register_waste
from app.waste.repositories.register_waste_repository import RegisterWasteRepository


ROLE_IDS = {
    "Administrator": 1,
    "Operations": 2,
    "Manager": 3,
}


class AprobacionLimiteVencidoTest(unittest.TestCase):

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
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))
            except Exception:
                db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    def _seed_alarma(self, waste_limit, lot_expiration=None):
        """Crea entorno con waste_limit configurable."""
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=30)

        waste_type = WasteType(
            name="Vencido", code="VENCIDO",
            severity="MEDIA", requires_approval=False,
            applies_central=False, is_active=True,
        )
        db.session.add(waste_type)
        db.session.flush()

        loc = Location(name="Sede Norte", state="Caracas")
        db.session.add(loc)
        db.session.flush()

        loc_origin = Location(name="Sede Origen", state="Caracas")
        db.session.add(loc_origin)
        db.session.flush()

        product = Product(
            name="Tomate", sku=f"TOM-{waste_type.id}-{waste_limit}",
            unit_of_measure="kg", waste_limit=waste_limit, is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        role = Role(id=ROLE_IDS["Operations"], name="Operations")
        db.session.add(role)
        db.session.flush()

        user = User(name="Operador", email=f"ops{waste_limit}@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add(user)
        db.session.flush()

        user.locations = [loc]
        db.session.flush()

        inv = Inventory(
            location_id=loc.id, product_id=product.id,
            current_quantity=100.0, transit_quantity=0.0, min_stock=20.0,
        )
        db.session.add(inv)

        mov = Movement(
            type="TRASLADO", origin_location_id=loc_origin.id,
            destination_location_id=loc.id, status="COMPLETED", user_id=user.id,
        )
        db.session.add(mov)
        db.session.flush()

        det = MovementDetail(
            movement_id=mov.id, product_id=product.id, lot_number="L-001",
            quantity=50.0, received_quantity=50.0, missing_quantity=0.0,
            expiration_date=lot_expiration,
        )
        db.session.add(det)
        db.session.commit()

        return {
            "waste_type": waste_type,
            "loc": loc,
            "product": product,
            "user": user,
        }

    # ------------------------------------------------------------------
    # 1) Merma VENCIDO cantidad < waste_limit → APROBADA (directa)
    # ------------------------------------------------------------------
    def test_vencido_cantidad_menor_limite_entra_aprobada_directa(self):
        """Cantidad 10 < waste_limit 20 → APROBADO sin pasar por admin."""
        env = self._seed_alarma(waste_limit=20.0)
        self._login(env["user"])

        # Deep link GET
        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        # POST
        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Merma por vencimiento bajo límite',
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'APROBADO')
        self.assertIn('waste_id', data)

        # Verificar en BD: merma APROBADA, stock descontado
        waste = Waste.query.get(data['waste_id'])
        self.assertEqual(waste.status, 'APROBADO')
        self.assertEqual(len(waste.details), 1)
        detail = waste.details[0]
        self.assertEqual(float(detail.quantity), 10.0)
        self.assertEqual(detail.waste_type_id, env["waste_type"].id)

        # Inventario descontado
        inv = Inventory.query.filter_by(
            product_id=env["product"].id, location_id=env["loc"].id
        ).first()
        self.assertEqual(float(inv.current_quantity), 90.0)

        # NO debe haber notificación de merma pendiente para admin
        notifs = Notification.query.filter_by(type='MERMA_PENDIENTE').all()
        self.assertEqual(len(notifs), 0)

    # ------------------------------------------------------------------
    # 2) Merma VENCIDO cantidad >= waste_limit → PENDIENTE + notifica admin
    # ------------------------------------------------------------------
    def test_vencido_cantidad_mayor_igual_limite_entra_pendiente_notifica_admin(self):
        """Cantidad 25 >= waste_limit 20 → PENDIENTE, notifica a administradores."""
        env = self._seed_alarma(waste_limit=20.0)
        self._login(env["user"])

        # Crear admin
        role_admin = Role(id=ROLE_IDS["Administrator"], name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin = User(name="Admin", email="admin@test.com",
                     password_hash="x", role_id=role_admin.id)
        db.session.add(admin)
        db.session.commit()

        # Deep link GET con cantidad 25
        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=25'
        )

        # POST
        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 25,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Merma por vencimiento supera límite',
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'PENDIENTE')
        self.assertIn('waste_id', data)

        # Verificar en BD: merma PENDIENTE
        waste = Waste.query.get(data['waste_id'])
        self.assertEqual(waste.status, 'PENDIENTE')

        # Stock NO descontado físicamente (solo reservado)
        inv = Inventory.query.filter_by(
            product_id=env["product"].id, location_id=env["loc"].id
        ).first()
        self.assertEqual(float(inv.current_quantity), 100.0)  # intacto

        # Disponibilidad del lote SÍ reducida (reservada)
        lots = RegisterWasteRepository.get_product_lots(env["product"].id, env["loc"].id)
        self.assertEqual(float(lots[0]['quantity']), 25.0)  # 50 - 25 reservado

        # Debe haber notificación MERMA_PENDIENTE para admin
        notifs = Notification.query.filter_by(type='MERMA_PENDIENTE').all()
        self.assertEqual(len(notifs), 1)
        notif = notifs[0]
        self.assertEqual(notif.user_id, admin.id)
        self.assertIn('pendiente', notif.message.lower())
        self.assertIn('Vencido', notif.message)

    # ------------------------------------------------------------------
    # 3) Límite exacto (cantidad == waste_limit) → PENDIENTE
    # ------------------------------------------------------------------
    def test_vencido_cantidad_igual_limite_entra_pendiente(self):
        """Cantidad 20 == waste_limit 20 → PENDIENTE (regla >=)."""
        env = self._seed_alarma(waste_limit=20.0)
        self._login(env["user"])

        # Crear admin para notificación
        role_admin = Role(id=ROLE_IDS["Administrator"], name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin = User(name="Admin", email="admin2@test.com",
                     password_hash="x", role_id=role_admin.id)
        db.session.add(admin)
        db.session.commit()

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=20'
        )

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 20,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Merma por vencimiento supera límite',
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'PENDIENTE')

        # Notificación creada
        notifs = Notification.query.filter_by(type='MERMA_PENDIENTE').all()
        self.assertEqual(len(notifs), 1)

    # ------------------------------------------------------------------
    # 4) Varios items en alarma (no permitido, pero verificar rechazo)
    # ------------------------------------------------------------------
    def test_alarma_vencido_rechaza_multi_item(self):
        """El deep link de alarma solo permite mono-ítem; multi-item → 400."""
        env = self._seed_alarma(waste_limit=50.0)
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        # Intentar POST con 2 items
        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [
                {'product_id': env["product"].id, 'lot_number': 'L-001', 'quantity': 5, 'waste_type_id': env["waste_type"].id},
                {'product_id': env["product"].id, 'lot_number': 'L-001', 'quantity': 5, 'waste_type_id': env["waste_type"].id},
            ],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('solo permite un ítem', response.get_json()['message'])

    # ------------------------------------------------------------------
    # 5) Verificar que al aprobar PENDIENTE el lote resta correctamente
    # ------------------------------------------------------------------
    def test_aprobacion_pendiente_resta_del_lote(self):
        """PENDIENTE reserva; al aprobar se mantiene la reserva (no doble descuento)."""
        env = self._seed_alarma(waste_limit=20.0)
        self._login(env["user"])

        role_admin = Role(id=ROLE_IDS["Administrator"], name="Administrator")
        db.session.add(role_admin)
        db.session.flush()
        admin = User(name="Admin", email="admin3@test.com",
                     password_hash="x", role_id=role_admin.id)
        db.session.add(admin)
        db.session.commit()

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=25'
        )

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 25,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Merma por vencimiento supera límite',
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        waste_id = data['waste_id']

        # Aprobar merma
        waste = Waste.query.get(waste_id)
        waste.status = 'APROBADO'
        db.session.commit()

        # Disponibilidad del lote: sigue 25 (50 - 25 reservado, al aprobar no descuenta extra)
        lots = RegisterWasteRepository.get_product_lots(env["product"].id, env["loc"].id)
        self.assertEqual(float(lots[0]['quantity']), 25.0)

        # Inventario físico sigue intacto (las mermas PENDIENTE no descuentan stock físico)
        inv = Inventory.query.filter_by(
            product_id=env["product"].id, location_id=env["loc"].id
        ).first()
        self.assertEqual(float(inv.current_quantity), 100.0)


if __name__ == "__main__":
    unittest.main()