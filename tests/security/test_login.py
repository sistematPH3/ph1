# =============================================================================
# INTEGRACIÓN DEL INICIO DE SESIÓN
# -----------------------------------------------------------------------------
# Cubre la regresión reportada: cuentas reales guardadas con el correo en
# mayúsculas (o con espacios) no podían entrar porque el login normalizaba a
# minúsculas y la búsqueda comparaba en crudo.
#
#   python -m unittest tests.security.test_login -v
# =============================================================================

import os
import unittest
from unittest.mock import patch

TEST_DATABASE_URL = os.environ.get(
    'TEST_DATABASE_URL',
    'postgresql://postgres:12345@localhost:5432/ph_test',
)
os.environ['DATABASE_URL'] = TEST_DATABASE_URL

from sqlalchemy import text  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import Location, LoginAudit, Role, User  # noqa: E402
from app.models.security_model import user_locations  # noqa: E402

PASSWORD = 'Ph12345.'
EMAIL_ADMIN = 'Admin.Login@Test.PH'      # se guarda con mayúsculas
EMAIL_OPS = 'ops.login@test.ph'
EMAIL_GUEST = 'guest.login@test.ph'


class LoginIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        self._limpiar()
        # Ids fijos del seeder de producción: el login enruta por rol.
        self.rol_guest = self._rol(0, 'Guest')
        self.rol_admin = self._rol(1, 'Administrator')
        self.rol_ops = self._rol(4, 'Operations')
        db.session.execute(text(
            "SELECT setval('roles_id_seq', (SELECT MAX(id) FROM roles))"
        ))
        self.sede = Location(name='Sede Login Test', state='Caracas',
                             is_active=True)
        db.session.add(self.sede)
        db.session.flush()

        self.admin = self._usuario(EMAIL_ADMIN, self.rol_admin.id,
                                   is_active=True)
        self.ops = self._usuario(EMAIL_OPS, self.rol_ops.id, is_active=True,
                                 locations=[self.sede])
        self.guest = self._usuario(EMAIL_GUEST, 0, is_active=False)
        db.session.commit()

    def tearDown(self):
        self._limpiar()
        db.session.delete(db.session.get(Location, self.sede.id))
        db.session.commit()
        self.ctx.pop()

    # ------------------------------------------------------------ helpers --
    def _rol(self, role_id, nombre):
        rol = db.session.get(Role, role_id)
        if rol is None:
            rol = Role(id=role_id, name=nombre)
            db.session.add(rol)
            db.session.flush()
        elif rol.name != nombre:
            # El id fijo ya está ocupado por otro rol: no lo renombramos.
            rol = Role(name=nombre)
            db.session.add(rol)
            db.session.flush()
        return rol

    def _usuario(self, email, role_id, is_active=True, locations=None):
        usuario = User(name=email.split('@')[0], email=email,
                       password_hash=generate_password_hash(PASSWORD),
                       role_id=role_id, is_active=is_active)
        usuario.locations = locations or []
        db.session.add(usuario)
        db.session.flush()
        return usuario

    def _limpiar(self):
        ids = [u.id for u in User.query.filter(
            User.email.in_([EMAIL_ADMIN, EMAIL_OPS, EMAIL_GUEST])).all()]
        if ids:
            LoginAudit.query.filter(LoginAudit.user_id.in_(ids)).delete(
                synchronize_session=False)
            db.session.execute(
                user_locations.delete().where(
                    user_locations.c.user_id.in_(ids))
            )
            User.query.filter(User.id.in_(ids)).delete(
                synchronize_session=False)
            db.session.commit()

    def _login(self, email, password=PASSWORD):
        return self.client.post(
            '/auth/login',
            data={'email': email, 'password': password},
            follow_redirects=False,
        )

    def _sesion_activa(self):
        with self.client.session_transaction() as sesion:
            return sesion.get('_user_id')

    def _ultimo_acceso(self, usuario, accion='INICIO_SESION'):
        return (LoginAudit.query
                .filter_by(user_id=usuario.id, action=accion)
                .order_by(LoginAudit.id.desc())
                .first())

    # -------------------------------------------------------------- casos --
    def test_credenciales_validas_inician_sesion_y_auditan(self):
        respuesta = self._login(EMAIL_ADMIN, PASSWORD)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/dashboard/admin', respuesta.headers['Location'])
        self.assertEqual(self._sesion_activa(), str(self.admin.id))

        acceso = self._ultimo_acceso(self.admin)
        self.assertIsNotNone(acceso, 'Debe registrarse el INICIO_SESION')
        self.assertEqual(acceso.action, 'INICIO_SESION')
        self.assertEqual(acceso.role_id, self.rol_admin.id)
        self.assertIsNone(acceso.location_id)

    def test_email_con_mayusculas_y_espacios_encuentra_la_cuenta(self):
        """Regresión: la cuenta se guardó como Admin.Login@Test.PH."""
        respuesta = self._login('  ADMIN.LOGIN@TEST.PH  ')
        self.assertEqual(respuesta.status_code, 302,
                         'El correo debe compararse sin distinguir mayúsculas')
        self.assertEqual(self._sesion_activa(), str(self.admin.id))
        self.assertIsNotNone(self._ultimo_acceso(self.admin))

    def test_usuario_de_sede_inicia_sesion_y_audita_su_sede(self):
        respuesta = self._login(EMAIL_OPS)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/dashboard/operations', respuesta.headers['Location'])
        self.assertEqual(self._sesion_activa(), str(self.ops.id))

        acceso = self._ultimo_acceso(self.ops)
        self.assertIsNotNone(acceso)
        self.assertEqual(acceso.location_id, self.sede.id)

    def test_invitado_pendiente_entra_a_sala_de_espera(self):
        respuesta = self._login(EMAIL_GUEST)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('waiting-room', respuesta.headers['Location'])
        self.assertEqual(self._sesion_activa(), str(self.guest.id))

    def test_password_incorrecta_no_inicia_sesion(self):
        respuesta = self._login(EMAIL_ADMIN, 'Incorrecta#1')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(self._sesion_activa())
        self.assertIsNone(self._ultimo_acceso(self.admin))

    def test_password_incorrecta_mantiene_mensaje_generico(self):
        """Un correo registrado nunca revela que la contraseña fue el fallo."""
        cuerpo = self._login(EMAIL_ADMIN, 'Incorrecta#1').get_data(as_text=True)
        self.assertIn('erróneos', cuerpo)
        self.assertNotIn('no está registrado', cuerpo)

    def test_correo_no_registrado_sugiere_el_registro(self):
        """Correo inexistente: mensaje propio en vez del genérico."""
        respuesta = self._login('nadie.registrado@test.ph', 'Ph12345.')
        cuerpo = respuesta.get_data(as_text=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(self._sesion_activa())
        self.assertIn('no está registrado', cuerpo)
        self.assertIn('Regístrate', cuerpo)
        self.assertNotIn('erróneos', cuerpo)

    def test_servicio_reporta_correo_no_registrado(self):
        from app.security.services.login_service import LoginService
        usuario, motivo = LoginService.autenticar(
            'nadie.registrado@test.ph', PASSWORD)
        self.assertIsNone(usuario)
        self.assertEqual(motivo, 'correo_no_registrado')

    def test_servicio_reporta_datos_incorrectos_con_correo_existente(self):
        from app.security.services.login_service import LoginService
        usuario, motivo = LoginService.autenticar(EMAIL_ADMIN, 'Incorrecta#1')
        self.assertIsNone(usuario)
        self.assertEqual(motivo, 'datos_incorrectos')

    def test_fallo_de_auditoria_no_bloquea_el_login(self):
        with patch('app.security.routes.login_routes.LoginAudit',
                   side_effect=RuntimeError('auditoria no disponible')):
            respuesta = self._login(EMAIL_ADMIN)
        self.assertEqual(respuesta.status_code, 302,
                         'Un fallo de auditoría no debe rechazar al usuario')
        self.assertEqual(self._sesion_activa(), str(self.admin.id))
        self.assertIsNone(self._ultimo_acceso(self.admin))


if __name__ == '__main__':
    unittest.main()
