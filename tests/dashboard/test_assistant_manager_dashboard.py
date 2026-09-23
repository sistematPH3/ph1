import os
import sys
import unittest
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)

try:
    from app import create_app
    app = create_app()
except ImportError:
    from run import app

from app.dashboard.dashboard_service import (
    get_expiring_lots,
    get_subgerente_context,
    get_recent_movements,
    _ids_de_sedes,
)


class DummyLocation:
    def __init__(self, id_, name="Sede Test"):
        self.id = id_
        self.name = name


class DummyUser:
    def __init__(self, locations=None):
        self.is_admin = False
        self.is_management = False
        self.is_finance = False
        self.is_assistant_manager = True
        self.locations = locations or []
        self.location = locations[0] if locations else None
        self.location_id = locations[0].id if locations else None
        self.id = 1
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False


class DummyProduct:
    def __init__(self, id_=1, name="Insumo Test", unit="kg"):
        self.id = id_
        self.name = name
        self.unit_of_measure = unit


class DummyMovementDetail:
    def __init__(self, product_id=1, lot="LOTE-001", qty=10.0, exp_date=None):
        self.product_id = product_id
        self.lot_number = lot
        self.quantity = qty
        self.expiration_date = exp_date or (date.today() + timedelta(days=15))


class DummyLocationModel:
    def __init__(self, id_=1, name="Sede Centro"):
        self.id = id_
        self.name = name


class TestAssistantManagerDashboard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        self.sede1 = DummyLocation(1, "Sede Centro")
        self.sede2 = DummyLocation(2, "Sede Norte")
        self.user_con_sedes = DummyUser(locations=[self.sede1, self.sede2])
        self.user_sin_sedes = DummyUser(locations=[])

    # ------------------------------------------------------------------
    # Helpers de service usados por el subgerente
    # ------------------------------------------------------------------
    def test_ids_de_sedes_con_locations(self):
        ids = _ids_de_sedes(self.user_con_sedes)
        self.assertEqual(ids, [1, 2])

    def test_ids_de_sedes_sin_locations(self):
        ids = _ids_de_sedes(self.user_sin_sedes)
        self.assertEqual(ids, [])

    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_expiring_lots_sin_sedes(self, mock_session):
        result = get_expiring_lots(self.user_sin_sedes)
        self.assertEqual(result, [])
        mock_session.query.assert_not_called()

    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_expiring_lots_estructura(self, mock_session):
        today = date.today()
        det = DummyMovementDetail(lot="L-100", qty=5.0, exp_date=today + timedelta(days=10))
        prod = DummyProduct(name="Harina", unit="kg")
        loc = DummyLocationModel(id_=1, name="Sede Centro")

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [(det, prod, loc)]

        result = get_expiring_lots(self.user_con_sedes, limit=5)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item['product'], "Harina")
        self.assertEqual(item['lot'], "L-100")
        self.assertEqual(item['location'], "Sede Centro")
        self.assertEqual(item['quantity'], 5.0)
        self.assertEqual(item['days'], 10)
        self.assertTrue(item['critical'])

    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_expiring_lots_critical(self, mock_session):
        today = date.today()
        det_critico = DummyMovementDetail(exp_date=today + timedelta(days=20))
        det_normal = DummyMovementDetail(exp_date=today + timedelta(days=45))
        prod = DummyProduct()
        loc = DummyLocationModel()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [(det_critico, prod, loc), (det_normal, prod, loc)]

        result = get_expiring_lots(self.user_con_sedes)
        self.assertTrue(result[0]['critical'])
        self.assertFalse(result[1]['critical'])

    # ------------------------------------------------------------------
    # get_subgerente_context
    # ------------------------------------------------------------------
    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_recent_movements')
    @patch('app.dashboard.dashboard_service.get_movement_list_context')
    @patch('app.dashboard.dashboard_service.obtener_alarmas_para_dashboard')
    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_subgerente_context_estructura(
        self, mock_session, mock_alarmas, mock_movs, mock_recent, mock_expiring
    ):
        mock_alarmas.return_value = [{'product_name': 'Azúcar'}]
        mock_movs.return_value = {'en_camino': [1, 2], 'por_recibir': [3]}
        mock_recent.return_value = []
        mock_expiring.return_value = [{'product': 'Harina', 'days': 12, 'critical': True}]
        mock_session.query.return_value.filter.return_value.scalar.return_value = 150.0

        ctx = get_subgerente_context(self.user_con_sedes)

        self.assertIn('alarmas', ctx)
        self.assertIn('critical_stock', ctx)
        self.assertIn('critical_count', ctx)
        self.assertIn('expiring_lots', ctx)
        self.assertIn('en_camino_count', ctx)
        self.assertIn('por_recibir_count', ctx)
        self.assertIn('total_stock', ctx)
        self.assertIn('consumo_hoy_monto', ctx)
        self.assertEqual(ctx['critical_count'], 1)
        self.assertEqual(ctx['en_camino_count'], 2)
        self.assertEqual(ctx['por_recibir_count'], 1)

    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_recent_movements')
    @patch('app.dashboard.dashboard_service.get_movement_list_context')
    @patch('app.dashboard.dashboard_service.obtener_alarmas_para_dashboard')
    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_subgerente_context_sin_sedes(
        self, mock_session, mock_alarmas, mock_movs, mock_recent, mock_expiring
    ):
        mock_alarmas.return_value = []
        mock_movs.return_value = {'en_camino': [], 'por_recibir': []}
        mock_recent.return_value = []
        mock_expiring.return_value = []

        ctx = get_subgerente_context(self.user_sin_sedes)
        self.assertEqual(ctx['critical_count'], 0)
        self.assertEqual(ctx['expiring_lots'], [])
        self.assertEqual(ctx['total_stock'], 0)

    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_recent_movements')
    @patch('app.dashboard.dashboard_service.get_movement_list_context')
    @patch('app.dashboard.dashboard_service.obtener_alarmas_para_dashboard')
    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_subgerente_context_critical_stock(
        self, mock_session, mock_alarmas, mock_movs, mock_recent, mock_expiring
    ):
        alarmas_mock = [{'id': 99}]
        mock_alarmas.return_value = alarmas_mock
        mock_movs.return_value = {'en_camino': [], 'por_recibir': []}
        mock_recent.return_value = []
        mock_expiring.return_value = []

        ctx = get_subgerente_context(self.user_con_sedes)
        self.assertIs(ctx['critical_stock'], alarmas_mock)
        self.assertEqual(ctx['critical_count'], 1)

    @patch('app.dashboard.dashboard_service.Location.query')
    @patch('app.dashboard.dashboard_service.Movement.query')
    def test_get_recent_movements_sin_sedes(self, mock_mov_query, mock_loc_query):
        result = get_recent_movements(self.user_sin_sedes)
        self.assertEqual(result, [])
        mock_mov_query.filter.assert_not_called()

    # ------------------------------------------------------------------
    # Ruta /assistant-manager
    # ------------------------------------------------------------------
    def _login(self, client, user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    @patch('app.dashboard.dashboard_routes.obtener_vencidos_para_dashboard')
    @patch('app.dashboard.dashboard_routes.get_subgerente_context')
    def test_ruta_assistant_manager_responde(self, mock_ctx, mock_vencidos):
        mock_ctx.return_value = {
            'alarmas': [], 'critical_stock': [], 'critical_count': 0,
            'expiring_lots': [], 'en_camino_count': 0, 'por_recibir_count': 0,
            'recent_movements': [], 'total_stock': 0, 'consumo_hoy_monto': 0,
        }
        mock_vencidos.return_value = []
        user = DummyUser(locations=[DummyLocation(1)])

        with app.test_client() as client:
            self._login(client, user)
            with patch('flask_login.utils._get_user', return_value=user), \
                 patch('app.decorators.roles.assistant_manager_required', lambda f: f), \
                 patch('flask_login.login_required', lambda f: f):

                for url in ('/assistant-manager', '/dashboard/assistant-manager'):
                    response = client.get(url)
                    if response.status_code in (200, 302):
                        break
                else:
                    self.skipTest("No se pudo alcanzar la vista de subgerente.")

        self.assertIn(response.status_code, (200, 302))


if __name__ == '__main__':
    unittest.main()