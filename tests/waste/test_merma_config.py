import unittest
import json
from app import create_app, db
from sqlalchemy import text

class TestMermaConfig(unittest.TestCase):

    def setUp(self):
        """Se ejecuta ANTES de cada prueba para preparar el entorno."""
        self.app = create_app()
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        """Se ejecuta DESPUÉS de cada prueba para limpiar la base de datos."""
        db.session.rollback()
        self.app_context.pop()

    def _login_admin(self):
        """Método auxiliar para simular la sesión de administrador."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = '1'
            sess['is_admin'] = True

    def test_update_waste_config_success(self):
        """Prueba que los parámetros válidos de mermas se actualicen correctamente."""
        self._login_admin()

        # Usamos el factor real de tolerancia (ejemplo: 1.50 para +50%)
        payload = {
            "WASTE_TIME_TOLERANCE": "1.50",
            "WASTE_BASE_PERIOD_DAYS": "14"
        }

        response = self.client.post(
            '/api/waste/merma/config',
            data=json.dumps(payload),
            content_type='application/json'
        )

        # Validar respuesta exitosa (200 OK)
        self.assertEqual(response.status_code, 200)

        # Verificar actualización directa en la Base de Datos
        tol_val = db.session.execute(
            text("SELECT value FROM public.app_parameters WHERE key = 'WASTE_TIME_TOLERANCE'")
        ).scalar()

        days_val = db.session.execute(
            text("SELECT value FROM public.app_parameters WHERE key = 'WASTE_BASE_PERIOD_DAYS'")
        ).scalar()

        self.assertEqual(float(tol_val), 1.50)
        self.assertEqual(int(days_val), 14)

    def test_update_waste_config_invalid_values(self):
        """Prueba que el sistema rechace valores fuera de rango o no válidos."""
        self._login_admin()

        # Enviamos valores inválidos (ejemplo: tolerancia menor a 1.00 o días fuera de límite)
        payload = {
            "WASTE_TIME_TOLERANCE": "0.50",
            "WASTE_BASE_PERIOD_DAYS": "999"
        }

        response = self.client.post(
            '/api/waste/merma/config',
            data=json.dumps(payload),
            content_type='application/json'
        )

        # Debe retornar 400 Bad Request debido a los errores de validación de WasteConfigValidators
        self.assertEqual(response.status_code, 400)
        
        data = response.get_json()
        self.assertFalse(data.get('success', True))
        self.assertIn('errors', data)

if __name__ == '__main__':
    unittest.main()