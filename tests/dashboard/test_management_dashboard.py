import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

# Garantizar el uso de la base de datos de pruebas
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)

try:
    from app import create_app
    app = create_app()
except ImportError:
    from run import app

import app.dashboard.dashboard_service as ds


class DummyLocation:
    """Simula un objeto de ubicación/sede en la BD."""
    def __init__(self, loc_id, name="Sede Test"):
        self.id = loc_id
        self.name = name


class DummyUser:
    """Simula a un usuario del sistema con sus sedes permitidas."""
    def __init__(self, user_id=1, name="Diego", locations=None):
        self.id = user_id
        self.name = name
        self.locations = locations or []


class TestManagementDashboard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Inicializa el contexto de la aplicación para las pruebas."""
        cls.app_context = app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        """Limpia el contexto de la aplicación."""
        cls.app_context.pop()

    def setUp(self):
        self.sede1 = DummyLocation(1, "PH Centro")
        self.sede2 = DummyLocation(2, "PH Norte")
        self.user_multisede = DummyUser(user_id=10, name="Gerente General", locations=[self.sede1, self.sede2])
        self.user_sin_sedes = DummyUser(user_id=11, name="Usuario Sin Sede", locations=[])

    def _setup_mock_query_chain(self, mock_query):
        """Helper para encadenar las llamadas de SQLAlchemy y evitar conexiones a BD real."""
        mock_chain = MagicMock()
        mock_query.return_value = mock_chain
        mock_chain.join.return_value = mock_chain
        mock_chain.filter.return_value = mock_chain
        mock_chain.order_by.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.scalar.return_value = 0.0
        mock_chain.count.return_value = 0
        mock_chain.all.return_value = []
        return mock_chain

    # =========================================================================
    # PRUEBAS DE get_expiring_lots (FILTRADO Y CÁLCULO DE VENCIMIENTOS)
    # =========================================================================

    @patch('app.extensions.db.session.query')
    def test_get_expiring_lots_filtra_por_sedes_de_usuario(self, mock_query):
        """Verifica que get_expiring_lots consulte usando las sedes asignadas al usuario."""
        self._setup_mock_query_chain(mock_query)

        res = ds.get_expiring_lots(self.user_multisede, limit=5, horizon_days=7)

        self.assertEqual(res, [])
        mock_query.assert_called_once()

    @patch('app.extensions.db.session.query')
    def test_get_expiring_lots_calculo_dias_y_criticidad(self, mock_query):
        """Verifica el cálculo de días restantes y marca de criticidad (critical <= 30 días)."""
        today = date.today()
        exp_date_3_days = today + timedelta(days=3)

        mock_det = MagicMock(expiration_date=exp_date_3_days, lot_number="LOT-100", quantity=15)
        
        # Asignación explícita de atributos para evitar conflictos con MagicMock(name=...)
        mock_prod = MagicMock(unit_of_measure="kg")
        mock_prod.name = "Queso Mozzarella"

        mock_loc = MagicMock()
        mock_loc.name = "PH Centro"

        mock_chain = self._setup_mock_query_chain(mock_query)
        mock_chain.all.return_value = [(mock_det, mock_prod, mock_loc)]

        lots = ds.get_expiring_lots(self.user_multisede, limit=5, horizon_days=7)

        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]['product'], "Queso Mozzarella")
        self.assertEqual(lots[0]['lot'], "LOT-100")
        self.assertEqual(lots[0]['days'], 3)
        self.assertTrue(lots[0]['critical'])

    def test_get_expiring_lots_usuario_sin_sedes_devuelve_lista_vacia(self):
        """Un usuario sin sedes no debe provocar errores y debe retornar lista vacía."""
        resultado = ds.get_expiring_lots(self.user_sin_sedes)
        self.assertEqual(resultado, [])

    # =========================================================================
    # PRUEBAS DE get_management_context (PANEL EJECUTIVO COMPLETO)
    # =========================================================================

    @patch.object(ds, 'get_expiring_lots')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    @patch.object(ds, 'get_movement_list_context')
    @patch('app.extensions.db.session.query')
    def test_management_context_modo_todas_las_sedes(
        self, mock_db_query, mock_mov_context, mock_alarmas, mock_vencidos, mock_expiring
    ):
        """Verifica que sin location_id se procesen todas las sedes asignadas al usuario."""
        mock_chain = self._setup_mock_query_chain(mock_db_query)
        mock_chain.scalar.return_value = 150.0

        mock_mov_context.return_value = {'en_camino': [], 'por_recibir': []}
        mock_alarmas.return_value = [{'location_id': 1}, {'location_id': 2}]
        mock_vencidos.return_value = [{'location_id': 1}]
        mock_expiring.return_value = [{'product': 'Masa', 'days': 2}]

        ctx = ds.get_management_context(self.user_multisede, location_id=None)

        self.assertIsNone(ctx['sede_seleccionada'])
        self.assertEqual(ctx['resumen']['stock_agregado'], 150.0)
        self.assertEqual(ctx['resumen']['cant_stock_bajo'], 2)
        self.assertEqual(ctx['resumen']['cant_vencidos'], 1)
        self.assertEqual(ctx['resumen']['alertas_criticas'], 3)
        mock_expiring.assert_called_once_with(self.user_multisede, limit=5, horizon_days=7)

    @patch.object(ds, 'get_expiring_lots')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    @patch.object(ds, 'get_movement_list_context')
    @patch('app.extensions.db.session.query')
    def test_management_context_filtra_correctamente_por_sede_seleccionada(
        self, mock_db_query, mock_mov_context, mock_alarmas, mock_vencidos, mock_expiring
    ):
        """Verifica que al seleccionar la sede 1, los conteos de alertas y lotes se restrinjan solo a esa sede."""
        mock_chain = self._setup_mock_query_chain(mock_db_query)
        mock_chain.scalar.return_value = 50.0

        mock_mov_context.return_value = {'en_camino': [], 'por_recibir': []}
        mock_alarmas.return_value = [{'location_id': 1}, {'location_id': 2}]
        mock_vencidos.return_value = [{'location_id': 1}, {'location_id': 2}]
        mock_expiring.return_value = [{'product': 'Pepperoni', 'days': 1}]

        ctx = ds.get_management_context(self.user_multisede, location_id=1)

        self.assertEqual(ctx['sede_seleccionada'], 1)
        self.assertEqual(len(ctx['alarmas']), 1)
        self.assertEqual(len(ctx['vencidos']), 1)
        self.assertEqual(ctx['resumen']['alertas_criticas'], 2)
        mock_expiring.assert_called_once_with(self.user_multisede, limit=5, horizon_days=7)

    @patch.object(ds, 'get_expiring_lots')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    @patch.object(ds, 'get_movement_list_context')
    @patch('app.extensions.db.session.query')
    def test_management_context_previene_vulnerabilidad_sede_no_autorizada(
        self, mock_db_query, mock_mov_context, mock_alarmas, mock_vencidos, mock_expiring
    ):
        """Seguridad: Si un usuario intenta consultar una sede no asignada (ej: id=999), debe ignorarla y usar sus sedes permitidas."""
        self._setup_mock_query_chain(mock_db_query)
        mock_mov_context.return_value = {}
        mock_alarmas.return_value = []
        mock_vencidos.return_value = []
        mock_expiring.return_value = []

        ctx = ds.get_management_context(self.user_multisede, location_id=999)

        self.assertIsNone(ctx['sede_seleccionada'])

    @patch('app.extensions.db.session.query')
    def test_management_context_tolerancia_a_nulls_en_base_de_datos(self, mock_db_query):
        """Verifica que si la BD retorna None en sumas de inventario no falle la aplicación."""
        mock_chain = self._setup_mock_query_chain(mock_db_query)
        mock_chain.scalar.return_value = None

        ctx = ds.get_management_context(self.user_sin_sedes)

        self.assertEqual(ctx['resumen']['stock_agregado'], 0.0)
        self.assertIsNone(ctx['resumen']['ultimo_ingreso'])
        self.assertEqual(ctx['resumen']['alertas_criticas'], 0)


if __name__ == '__main__':
    unittest.main()