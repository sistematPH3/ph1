import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

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
    """Simula una sede/ubicación en la base de datos."""
    def __init__(self, loc_id, name="Sede Test"):
        self.id = loc_id
        self.name = name


class DummyUser:
    """Simula un usuario con sedes permitidas asignadas."""
    def __init__(self, user_id=1, name="Diego Operaciones", locations=None):
        self.id = user_id
        self.name = name
        self.locations = locations or []


class DummyMovement:
    """Simula un movimiento/traslado de la base de datos."""
    def __init__(self, mov_id, origin_id, dest_id, status="EN_TRANSITO", movement_type="TRASLADO"):
        self.id = mov_id
        self.origin_location_id = origin_id
        self.destination_location_id = dest_id
        self.status = status
        self.date = datetime.now()
        self.type = movement_type


class TestOperationsDashboard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Inicializa el contexto de Flask para la ejecución de pruebas."""
        cls.app_context = app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        """Limpia el contexto de Flask al finalizar la suite."""
        cls.app_context.pop()

    def setUp(self):
        """Configuración básica de entidades previas a cada prueba."""
        self.sede1 = DummyLocation(1, "PH Centro")
        self.sede2 = DummyLocation(2, "PH Norte")
        self.user_operaciones = DummyUser(user_id=20, name="Operador 1", locations=[self.sede1, self.sede2])
        self.user_sin_sedes = DummyUser(user_id=21, name="Operador Sin Sede", locations=[])

    def _setup_mock_query_chain(self, mock_query):
        """Helper para emular las llamadas encadenadas del ORM de SQLAlchemy."""
        mock_chain = MagicMock()
        mock_query.filter.return_value = mock_chain
        mock_query.order_by.return_value = mock_chain
        mock_chain.filter.return_value = mock_chain
        mock_chain.order_by.return_value = mock_chain
        mock_chain.limit.return_value = mock_chain
        mock_chain.count.return_value = 0
        mock_chain.all.return_value = []
        return mock_chain

    @patch('app.models.Location')
    @patch('app.models.Movement')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    def test_operations_context_modo_todas_las_sedes(
        self, mock_alarmas, mock_vencidos, mock_movement, mock_location
    ):
        """Verifica la agregación de métricas sin filtro de sede (todas las sedes asignadas)."""
        mock_location.query.all.return_value = [self.sede1, self.sede2]
        self._setup_mock_query_chain(mock_movement.query)
        
        mock_alarmas.return_value = [{'location_id': 1, 'producto': 'Masa'}]
        mock_vencidos.return_value = [{'location_id': 1, 'producto': 'Tomate'}, {'location_id': 2, 'producto': 'Queso'}]

        ctx = ds.get_operations_context(self.user_operaciones, location_id=None)

        self.assertIsNone(ctx['sede_seleccionada'])
        self.assertEqual(len(ctx['sedes']), 2)
        self.assertEqual(ctx['resumen']['mermas_count'], 2)
        self.assertEqual(len(ctx['alarmas_stock']), 1)
        self.assertEqual(len(ctx['vencidos']), 2)

    @patch('app.models.Location')
    @patch('app.models.Movement')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    def test_operations_context_filtro_por_sede_especifica(
        self, mock_alarmas, mock_vencidos, mock_movement, mock_location
    ):
        """Verifica que al filtrar por una sede válida, solo se devuelvan alertas de esa sede."""
        mock_location.query.all.return_value = [self.sede1, self.sede2]
        self._setup_mock_query_chain(mock_movement.query)

        mock_alarmas.return_value = [{'location_id': 1, 'producto': 'Harina'}, {'location_id': 2, 'producto': 'Salsa'}]
        mock_vencidos.return_value = [{'location_id': 1, 'producto': 'Jamón'}]

        ctx = ds.get_operations_context(self.user_operaciones, location_id=1)

        self.assertEqual(ctx['sede_seleccionada'], 1)
        self.assertEqual(len(ctx['alarmas_stock']), 1)
        self.assertEqual(ctx['alarmas_stock'][0]['producto'], 'Harina')
        self.assertEqual(len(ctx['vencidos']), 1)

    @patch('app.models.Location')
    @patch('app.models.Movement')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    def test_operations_context_previene_acceso_a_sede_no_autorizada(
        self, mock_alarmas, mock_vencidos, mock_movement, mock_location
    ):
        """Seguridad: Si se pasa un id de sede no asignado al usuario (ej: 999), debe ignorarse."""
        mock_location.query.all.return_value = [self.sede1, self.sede2]
        self._setup_mock_query_chain(mock_movement.query)
        mock_alarmas.return_value = []
        mock_vencidos.return_value = []

        ctx = ds.get_operations_context(self.user_operaciones, location_id=999)

        self.assertIsNone(ctx['sede_seleccionada'])

    @patch('app.models.Location')
    @patch('app.models.Movement')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    def test_operations_context_mapeo_de_recepciones_pendientes(
        self, mock_alarmas, mock_vencidos, mock_movement, mock_location
    ):
        """Verifica la construcción correcta de los objetos 'recepciones_pendientes'."""
        mock_location.query.all.return_value = [self.sede1, self.sede2]
        
        mov1 = DummyMovement(mov_id=101, origin_id=2, dest_id=1, status="EN_TRANSITO", movement_type="TRASLADO")
        
        
        mock_chain = self._setup_mock_query_chain(mock_movement.query)
        mock_movement.query = mock_chain
        mock_chain.filter.return_value = mock_chain
        mock_chain.order_by.return_value = mock_chain

        mock_chain.all.side_effect = [
            [mov1], 
            [mov1], 
            []      
        ]

        mock_alarmas.return_value = []
        mock_vencidos.return_value = []

        ctx = ds.get_operations_context(self.user_operaciones, location_id=None)

        self.assertIn('recepciones_pendientes', ctx)
        self.assertEqual(len(ctx['recepciones_pendientes']), 1)
        self.assertEqual(ctx['recepciones_pendientes'][0]['id'], 101)
        self.assertEqual(ctx['recepciones_pendientes'][0]['origen'], 'PH Norte')
        self.assertEqual(ctx['recepciones_pendientes'][0]['destino'], 'PH Centro')

    @patch('app.models.Location')
    @patch('app.models.Movement')
    @patch.object(ds, 'obtener_vencidos_para_dashboard')
    @patch.object(ds, 'obtener_alarmas_para_dashboard')
    def test_operations_context_usuario_sin_sedes_retorna_estructuras_vacias(
        self, mock_alarmas, mock_vencidos, mock_movement, mock_location
    ):
        """Garantiza estabilidad cuando el usuario no tiene ninguna sede asignada."""
        mock_location.query.all.return_value = []
        self._setup_mock_query_chain(mock_movement.query)
        mock_alarmas.return_value = []
        mock_vencidos.return_value = []

        ctx = ds.get_operations_context(self.user_sin_sedes)

        self.assertEqual(ctx['sedes'], [])
        self.assertIsNone(ctx['sede_seleccionada'])
        self.assertEqual(ctx['resumen']['en_transito_count'], 0)
        self.assertEqual(ctx['resumen']['cant_recepciones_pendientes'], 0)
        self.assertEqual(ctx['recepciones_pendientes'], [])


if __name__ == '__main__':
    unittest.main()