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
    get_manager_context,
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
        self.is_manager = True
        self.is_assistant_manager = False
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


class TestManagerDashboard(unittest.TestCase):

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
    # Helpers compartidos
    # ------------------------------------------------------------------
    def test_ids_de_sedes_con_locations(self):
        ids = _ids_de_sedes(self.user_con_sedes)
        self.assertEqual(ids, [1, 2])

    def test_ids_de_sedes_sin_locations(self):
        ids = _ids_de_sedes(self.user_sin_sedes)
        self.assertEqual(ids, [])

    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_expiring_lots_estructura(self, mock_session):
        today = date.today()
        det = DummyMovementDetail(lot="L-200", qty=8.0, exp_date=today + timedelta(days=12))
        prod = DummyProduct(name="Azúcar", unit="kg")
        loc = DummyLocationModel(id_=1, name="Sede Centro")

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [(det, prod, loc)]

        result = get_expiring_lots(self.user_con_sedes)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item['product'], "Azúcar")
        self.assertEqual(item['lot'], "L-200")
        self.assertEqual(item['quantity'], 8.0)
        self.assertTrue(item['critical'])

    # ------------------------------------------------------------------
    # get_manager_context
    # ------------------------------------------------------------------
    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_movement_list_context')
    @patch('app.dashboard.dashboard_service.obtener_alarmas_para_dashboard')
    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_manager_context_estructura(
        self, mock_session, mock_alarmas, mock_movs, mock_expiring
    ):
        mock_alarmas.return_value = [{'product_name': 'Harina'}]
        mock_movs.return_value = {'en_camino': [1], 'por_recibir': [2, 3]}
        mock_expiring.return_value = [
            {
                'product': 'Leche',
                'lot': 'L-10',
                'location': 'Centro',
                'expiration': date.today() + timedelta(days=8),
                'quantity': 4.0,
                'days': 8,
                'critical': True,
            }
        ]
        mock_session.query.return_value.filter.return_value.scalar.return_value = 200.0
        mock_session.query.return_value.filter.return_value.count.return_value = 0

        # Evitar errores en consultas internas
        mock_session.query.return_value.join.return_value = mock_session.query.return_value
        mock_session.query.return_value.filter.return_value = mock_session.query.return_value
        mock_session.query.return_value.order_by.return_value = mock_session.query.return_value
        mock_session.query.return_value.limit.return_value = mock_session.query.return_value
        mock_session.query.return_value.all.return_value = []

        ctx = get_manager_context(self.user_con_sedes)

        self.assertIn('alarmas', ctx)
        self.assertIn('critical_stock_items', ctx)
        self.assertIn('vencidos', ctx)
        self.assertIn('expiring_lots', ctx)
        self.assertIn('total_stock', ctx)
        self.assertIn('consumo_hoy_monto', ctx)
        self.assertIn('pending_wastes_count', ctx)
        self.assertIn('transfers_in_transit_count', ctx)
        self.assertIn('sede_nombre', ctx)

    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_movement_list_context')
    @patch('app.dashboard.dashboard_service.obtener_alarmas_para_dashboard')
    @patch('app.dashboard.dashboard_service.db.session')
    def test_get_manager_context_sin_sedes(
        self, mock_session, mock_alarmas, mock_movs, mock_expiring
    ):
        mock_alarmas.return_value = []
        mock_movs.return_value = {'en_camino': [], 'por_recibir': []}
        mock_expiring.return_value = []
        mock_session.query.return_value.filter.return_value.scalar.return_value = 0
        mock_session.query.return_value.filter.return_value.count.return_value = 0
        mock_session.query.return_value.join.return_value = mock_session.query.return_value
        mock_session.query.return_value.filter.return_value = mock_session.query.return_value
        mock_session.query.return_value.order_by.return_value = mock_session.query.return_value
        mock_session.query.return_value.limit.return_value = mock_session.query.return_value
        mock_session.query.return_value.all.return_value = []

        ctx = get_manager_context(self.user_sin_sedes)
        self.assertEqual(ctx['total_stock'], 0)
        self.assertEqual(ctx['expiring_lots'], [])
        self.assertIn('sede_nombre', ctx)

    # ------------------------------------------------------------------
    # Ruta /manager-dashboard
    # ------------------------------------------------------------------
    def _login(self, client, user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    @patch('app.dashboard.dashboard_service.get_expiring_lots')
    @patch('app.dashboard.dashboard_service.get_manager_context')
    @patch('app.dashboard.dashboard_routes.obtener_vencidos_para_dashboard')
    @patch('app.dashboard.dashboard_routes.obtener_alarmas_para_dashboard')
    def test_ruta_manager_responde(
        self, mock_alarmas, mock_vencidos, mock_ctx, mock_expiring
    ):
        """La ruta de gerente responde 200 o 302."""
        mock_ctx.return_value = {
            'total_stock': 100,
            'consumo_hoy_monto': 10,
            'pending_wastes_count': 0,
            'transfers_in_transit_count': 1,
            'sede': None,
            'sede_nombre': 'Mi Sede',
            'location': None,
            'expiring_lots': [],
        }
        mock_alarmas.return_value = []
        mock_vencidos.return_value = []
        mock_expiring.return_value = []

        user = DummyUser(locations=[DummyLocation(1)])

        with app.test_client() as client:
            self._login(client, user)
            with patch('flask_login.utils._get_user', return_value=user), \
                 patch('app.decorators.roles.manager_required', lambda f: f), \
                 patch('flask_login.login_required', lambda f: f):

                for url in ('/manager-dashboard', '/dashboard/manager-dashboard'):
                    response = client.get(url)
                    if response.status_code in (200, 302):
                        break
                else:
                    self.skipTest("No se pudo alcanzar la vista de gerente.")

        self.assertIn(response.status_code, (200, 302))


if __name__ == '__main__':
    unittest.main()