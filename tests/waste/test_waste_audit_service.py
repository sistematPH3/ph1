import os
import unittest
from unittest.mock import MagicMock, patch

# Usa SIEMPRE la base de pruebas (ph_test), nunca la base real (ph). Debe
# fijarse ANTES de importar la app porque app crea el motor leyendo
# config['SQLALCHEMY_DATABASE_URI'] en el arranque.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)

# Intentar importar la aplicación Flask según la estructura del proyecto
try:
    from app import create_app
    app = create_app()
except ImportError:
    from run import app

from app.waste.services.waste_audit_service import WasteAuditService


class DummyUser:
    """Usuario simulado para pruebas de permisos."""
    def __init__(self, is_admin=True, locations=None):
        self.is_admin = is_admin
        self.is_management = False
        self.is_finance = False
        self.locations = locations or []


class DummyLog:
    """Objeto mock que simula un registro de auditoría devuelto por la base de datos."""
    def __init__(self, log_id, action, changed_data, timestamp=None, user=None, location=None, severity='NORMAL'):
        self.id = log_id
        self.action = action
        self.changed_data = changed_data
        self.timestamp = timestamp
        self.user = user
        self.location = location
        self.severity = severity


class TestWasteAuditService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Inicializa el contexto de aplicación de Flask para toda la suite de pruebas."""
        cls.app_context = app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        """Elimina el contexto de aplicación al finalizar todas las pruebas."""
        cls.app_context.pop()

    def setUp(self):
        self.admin_user = DummyUser(is_admin=True)

    @patch('app.waste.repositories.waste_audit_repository.WasteAuditRepository.get_audit_logs')
    @patch('app.models.waste_model.Waste.query')
    def test_audit_trail_creation_event_is_pending(self, mock_waste_query, mock_get_logs):
        """Verifica que un log con acción CREAR devuelva estado PENDIENTE."""
        mock_log = DummyLog(
            log_id=1,
            action='CREAR',
            changed_data={
                'merma_id': 10,
                'tipo_merma': 'Sobreproduccion',
                'productos': [{'producto': 'Helado', 'cantidad': 2}],
                'motivo_registro': 'Sobrante de lote'
            }
        )
        mock_get_logs.return_value = [mock_log]
        mock_waste_query.get.return_value = None

        result = WasteAuditService.get_formatted_audit_trail(self.admin_user, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'PENDIENTE')
        self.assertFalse(result[0]['is_reverted'])

    @patch('app.waste.repositories.waste_audit_repository.WasteAuditRepository.get_audit_logs')
    @patch('app.models.waste_model.Waste.query')
    def test_audit_trail_approval_event_is_approved(self, mock_waste_query, mock_get_logs):
        """Verifica que un log con acción APROBAR devuelva estado APROBADO."""
        mock_log = DummyLog(
            log_id=2,
            action='APROBAR',
            changed_data={
                'merma_id': 10,
                'aprobado_por': 'Diego Chirinos'
            }
        )
        mock_get_logs.return_value = [mock_log]
        mock_waste_query.get.return_value = None

        result = WasteAuditService.get_formatted_audit_trail(self.admin_user, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'APROBADO')
        self.assertFalse(result[0]['is_reverted'])

    @patch('app.waste.repositories.waste_audit_repository.WasteAuditRepository.get_audit_logs')
    @patch('app.models.waste_model.Waste.query')
    def test_audit_trail_rejection_event_is_rejected(self, mock_waste_query, mock_get_logs):
        """Verifica que un log con acción RECHAZO devuelva estado RECHAZADO."""
        mock_log = DummyLog(
            log_id=3,
            action='RECHAZO',
            changed_data={
                'merma_id': 11,
                'motivo_rechazo': 'Información incompleta'
            }
        )
        mock_get_logs.return_value = [mock_log]
        mock_waste_query.get.return_value = None

        result = WasteAuditService.get_formatted_audit_trail(self.admin_user, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'RECHAZADO')

    @patch('app.waste.repositories.waste_audit_repository.WasteAuditRepository.get_audit_logs')
    @patch('app.models.waste_model.Waste.query')
    def test_audit_trail_reverted_waste_sets_is_reverted_true(self, mock_waste_query, mock_get_logs):
        """Verifica que si la merma original está REVERTIDA en BD, is_reverted sea True."""
        mock_waste_obj = MagicMock()
        mock_waste_obj.status = 'REVERTIDO'
        mock_waste_query.get.return_value = mock_waste_obj

        mock_log = DummyLog(
            log_id=4,
            action='APROBACION',
            changed_data={'merma_id': 12}
        )
        mock_get_logs.return_value = [mock_log]

        result = WasteAuditService.get_formatted_audit_trail(self.admin_user, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'APROBADO')
        self.assertTrue(result[0]['is_reverted'])

    @patch('app.waste.repositories.waste_audit_repository.WasteAuditRepository.get_audit_logs')
    @patch('app.models.waste_model.Waste.query')
    def test_audit_trail_handles_edited_waste(self, mock_waste_query, mock_get_logs):
        """Verifica que eventos de EDICION o CORRECCION se registren como PENDIENTE."""
        mock_log = DummyLog(
            log_id=5,
            action='EDICION',
            changed_data={
                'merma_id': 13,
                'motivo': 'Cantidad corregida'
            }
        )
        mock_get_logs.return_value = [mock_log]
        mock_waste_query.get.return_value = None

        result = WasteAuditService.get_formatted_audit_trail(self.admin_user, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'PENDIENTE')


if __name__ == '__main__':
    unittest.main()