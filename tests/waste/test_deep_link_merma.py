# =============================================================================
# PRUEBAS DEL DEEP LINK DE ALARMA DE VENCIDOS (FAMILIA B)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) GET válido → prefill bloqueado con datos correctos
#   2) Sede sin permiso → 403
#   3) Lote inexistente o ya no vencido → error y redirección
#   4) Cantidad > saldo → 400
#   5) POST alterando producto/lote/cantidad/motivo → 400
#   6) POST válido → merma creada mono-ítem VENCIDO
#   7) POST sin sesión alarma → 400
#   8) Central sin vencido_permitido_en_central → 400
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
from flask import session
from app.models import (
    Inventory, Location, Movement, MovementDetail, Product, Role, User, WasteType, Waste,
)
from app.waste.services.register_waste_service import register_waste
from app.waste.repositories.register_waste_repository import RegisterWasteRepository


ROLE_IDS = {
    "Administrator": 1,
    "Operations": 2,
    "Manager": 3,
}


class DeepLinkMermaTest(unittest.TestCase):

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

    def _seed_alarma(self, lot_expiration=None, central=False):
        """Crea entorno: tipo VENCIDO, sede, producto, lote vencido con saldo, usuario."""
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=30)

        waste_type = WasteType(
            name="Vencido", code="VENCIDO",
            severity="MEDIA", requires_approval=False,
            applies_central=False, is_active=True,
        )
        db.session.add(waste_type)
        db.session.flush()

        # Crear sedes: Central primero para id=1
        loc_central = Location(name="Sede Central", state="Caracas")
        loc_norte = Location(name="Sede Norte", state="Caracas")
        db.session.add_all([loc_central, loc_norte])
        db.session.flush()
        assert loc_central.id == 1

        if central:
            loc = loc_central
        else:
            loc = loc_norte

        loc_origin = Location(name="Sede Origen", state="Caracas")
        db.session.add(loc_origin)
        db.session.flush()

        product = Product(
            name="Tomate", sku=f"TOM-{waste_type.id}",
            unit_of_measure="kg", waste_limit=20.0, is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        role = Role(id=ROLE_IDS["Operations"], name="Operations")
        db.session.add(role)
        db.session.flush()

        user = User(name="Operador", email="ops@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add(user)
        db.session.flush()

        # Usuario asignado a la sede
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
            "lot_expiration": lot_expiration,
        }

    # ------------------------------------------------------------------
    # 1) GET válido → prefill bloqueado
    # ------------------------------------------------------------------
    def test_get_deep_link_valido_devuelve_prefill_bloqueado(self):
        env = self._seed_alarma()
        self._login(env["user"])

        with self.client.session_transaction() as sess:
            sess['alarma_vencido'] = {}

        response = self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Verificar que el template recibe alarm_prefill
        self.assertIn('Merma asistida por alarma de vencidos', html)
        # Campos bloqueados (disabled)
        self.assertIn('disabled', html)
        # Cantidad 10 en el formulario
        self.assertIn('10', html)

        # Sesión poblada
        with self.client.session_transaction() as sess:
            self.assertIn('alarma_vencido', sess)
            alarm = sess['alarma_vencido']
            self.assertEqual(alarm['location_id'], env["loc"].id)
            self.assertEqual(alarm['product_id'], env["product"].id)
            self.assertEqual(alarm['lot_number'], 'L-001')
            self.assertEqual(alarm['quantity'], 10.0)

    # ------------------------------------------------------------------
    # 2) Sede sin permiso → 403 (redirección con flash)
    # ------------------------------------------------------------------
    def test_get_sede_sin_permiso_redirecciona(self):
        env = self._seed_alarma()
        # Usuario SIN sede asignada
        env["user"].locations = []
        db.session.commit()
        self._login(env["user"])

        response = self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10',
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)  # redirige a nueva_merma
        html = response.get_data(as_text=True)
        self.assertIn('No tienes permisos para acceder a esta sede', html)

    # ------------------------------------------------------------------
    # 3) Lote inexistente o ya no vencido → error y redirección
    # ------------------------------------------------------------------
    def test_get_lote_ya_no_vencido_redirecciona(self):
        env = self._seed_alarma(lot_expiration=date.today() + timedelta(days=10))  # vigente
        self._login(env["user"])

        response = self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10',
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('ya no est', html)  # "ya no está vencido"

    # ------------------------------------------------------------------
    # 4) Cantidad > saldo → 400
    # ------------------------------------------------------------------
    def test_get_cantidad_mayor_saldo_redirecciona(self):
        env = self._seed_alarma()  # saldo 50
        self._login(env["user"])

        response = self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=100',  # > 50
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('supera el saldo disponible', html)

    # ------------------------------------------------------------------
    # 5) POST alterando campos → 400
    # ------------------------------------------------------------------
    def test_post_alterando_producto_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        # Primero GET para poblar sesión
        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        # POST con product_id diferente
        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': 99999,  # distinto
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('no coinciden con la alarma original', response.get_json()['message'])

    def test_post_alterando_lote_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-999',  # distinto
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('no coinciden con la alarma original', response.get_json()['message'])

    def test_post_alterando_cantidad_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 999,  # distinto
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('no coinciden con la alarma original', response.get_json()['message'])

    def test_post_alterando_motivo_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        # Crear otro tipo de merma
        wt2 = WasteType(name="Dañado", code="DANIADO", severity="ALTA",
                        requires_approval=False, applies_central=False, is_active=True)
        db.session.add(wt2)
        db.session.commit()

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': wt2.id,  # no VENCIDO
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('tipo de merma debe ser VENCIDO', response.get_json()['message'])

    def test_post_alterando_sede_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        # Crear otra sede
        loc2 = Location(name="Sede Sur", state="Caracas")
        db.session.add(loc2)
        db.session.commit()

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': loc2.id,  # distinta
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('no coinciden con la alarma original', response.get_json()['message'])

    # ------------------------------------------------------------------
    # 6) POST válido → merma creada mono-ítem VENCIDO
    # ------------------------------------------------------------------
    def test_post_valido_crea_merma_mono_item_vencido(self):
        env = self._seed_alarma()
        self._login(env["user"])

        self.client.get(
            f'/waste/merma/new?origin=alarma_vencido&lock=1'
            f'&location_id={env["loc"].id}'
            f'&product_id={env["product"].id}'
            f'&lot_number=L-001'
            f'&quantity=10'
        )

        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Merma por alarma de vencidos',
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'APROBADO')  # cantidad 10 < waste_limit 20
        self.assertIn('waste_id', data)

        # Verificar en BD
        waste = Waste.query.get(data['waste_id'])
        self.assertEqual(waste.status, 'APROBADO')
        self.assertEqual(len(waste.details), 1)
        detail = waste.details[0]
        self.assertEqual(detail.product_id, env["product"].id)
        self.assertEqual(detail.lot_number, 'L-001')
        self.assertEqual(float(detail.quantity), 10.0)
        self.assertEqual(detail.waste_type_id, env["waste_type"].id)

        # Sesión limpiada
        with self.client.session_transaction() as sess:
            self.assertNotIn('alarma_vencido', sess)

    # ------------------------------------------------------------------
    # 7) POST sin sesión alarma → 400
    # ------------------------------------------------------------------
    def test_post_sin_sesion_alarma_devuelve_400(self):
        env = self._seed_alarma()
        self._login(env["user"])

        # NO hacemos GET previo, sesión vacía
        response = self.client.post('/waste/merma/new', json={
            'origin': 'alarma_vencido',
            'location_id': env["loc"].id,
            'items': [{
                'product_id': env["product"].id,
                'lot_number': 'L-001',
                'quantity': 10,
                'waste_type_id': env["waste_type"].id,
            }],
            'notes': 'Test note',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('expiraron', response.get_json()['message'])

    # ------------------------------------------------------------------
    # 8) Central sin vencido_permitido_en_central → 400
    # ------------------------------------------------------------------
    def test_get_central_sin_permiso_vencidos_redirecciona(self):
        env = self._seed_alarma(central=True)
        self._login(env["user"])

        # Mock: Central no permite vencidos
        from app.waste.repositories.register_waste_repository import RegisterWasteRepository
        original = RegisterWasteRepository.vencido_permitido_en_central
        RegisterWasteRepository.vencido_permitido_en_central = lambda: False

        try:
            response = self.client.get(
                f'/waste/merma/new?origin=alarma_vencido&lock=1'
                f'&location_id=1'
                f'&product_id={env["product"].id}'
                f'&lot_number=L-001'
                f'&quantity=10',
                follow_redirects=True
            )
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('no permite registro de vencidos', html)
        finally:
            RegisterWasteRepository.vencido_permitido_en_central = original


if __name__ == "__main__":
    unittest.main()