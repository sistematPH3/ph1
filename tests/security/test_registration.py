"""Pruebas del registro de usuarios.

Cada caso cubre un bug corregido:
- validacion en cascada que devolvia solo un error y ademas marcaba
  "limite alcanzado" como fallo justo en el caracter 12, que es valido,
- la plantilla filtraba los avisos de contrasena y de formato, dejando al
  usuario ante un formulario vacio sin saber que habia fallado,
- /check-email podia devolver 415 en HTML y romper el JS,
- reglas duplicadas entre el HTML, el JS y el backend,
- alta con role_id 0 (invitado) e is_active True, que permitia iniciar
  sesion sin pasar por la aprobacion del administrador.
"""
import os
import unittest

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _asegurar_bd_pruebas():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not existe:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_asegurar_bd_pruebas()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.security.repositories.user_management_repository import (  # noqa: E402
    UserManagementRepository,
)
from app.security.requests.auth_validators import REGLAS_PASSWORD  # noqa: E402
from app.security.requests.register_validators import validar_datos_registro  # noqa: E402
from app.security.routes import register_routes  # noqa: E402
from app.security.services.login_service import LoginService  # noqa: E402
from app.security.services.register_service import RegisterService  # noqa: E402
from werkzeug.security import check_password_hash  # noqa: E402

CORREO = 'nuevo@prueba.test'
NOMBRE = 'Persona Nueva'
PASSWORD_OK = 'Prueba#1'


class TestValidacion(unittest.TestCase):
    """El contrato (es_valido, mensaje) y los limites de longitud."""

    def setUp(self):
        # El validador consulta la base para descartar correos duplicados, asi
        # que necesita contexto de aplicacion.
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.ctx = self.app.app_context()
        self.ctx.push()
        User.query.filter_by(email=CORREO).delete()
        db.session.commit()

    def tearDown(self):
        User.query.filter_by(email=CORREO).delete()
        db.session.remove()
        self.ctx.pop()

    def test_contrato_devuelve_tupla(self):
        resultado = validar_datos_registro(NOMBRE, CORREO, PASSWORD_OK)
        self.assertIsInstance(resultado, tuple)
        self.assertEqual(len(resultado), 2)
        es_valido, mensaje = resultado
        self.assertTrue(es_valido)
        self.assertEqual(mensaje, "")

    def test_exacto_12_caracteres_es_valido(self):
        """Bug: el JS comparaba con === 12 y marcaba error en el limite valido."""
        self.assertEqual(REGLAS_PASSWORD['max_length'], 12)
        limite = 'Ab1#' + 'x' * 8  # 4 + 8 = 12
        self.assertEqual(len(limite), 12)
        es_valido, _ = validar_datos_registro(NOMBRE, CORREO, limite)
        self.assertTrue(es_valido, "12 caracteres es el maximo permitido, no un error")

    def test_exacto_6_caracteres_es_valido(self):
        minimo = 'Ab1#ef'  # 6
        self.assertEqual(len(minimo), 6)
        es_valido, _ = validar_datos_registro(NOMBRE, CORREO, minimo)
        self.assertTrue(es_valido, "6 caracteres es el minimo permitido")

    def test_13_caracteres_es_invalido(self):
        largo = 'Ab1#' + 'x' * 9  # 13
        self.assertEqual(len(largo), 13)
        es_valido, mensaje = validar_datos_registro(NOMBRE, CORREO, largo)
        self.assertFalse(es_valido)
        self.assertIn('entre 6 y 12', mensaje)

    def test_5_caracteres_es_invalido(self):
        es_valido, mensaje = validar_datos_registro(NOMBRE, CORREO, 'Ab1#e')
        self.assertFalse(es_valido)
        self.assertIn('entre 6 y 12', mensaje)

    def test_sin_mayuscula_es_invalido(self):
        es_valido, mensaje = validar_datos_registro(NOMBRE, CORREO, 'prueba#1')
        self.assertFalse(es_valido)
        self.assertIn('may', mensaje.lower())

    def test_sin_especial_es_invalido(self):
        es_valido, mensaje = validar_datos_registro(NOMBRE, CORREO, 'Prueba11')
        self.assertFalse(es_valido)
        self.assertIn('especial', mensaje.lower())

    def test_nombre_vacio_es_invalido(self):
        es_valido, mensaje = validar_datos_registro('   ', CORREO, PASSWORD_OK)
        self.assertFalse(es_valido)
        self.assertIn('nombre', mensaje.lower())

    def test_nombre_sobrante_40_es_invalido(self):
        es_valido, mensaje = validar_datos_registro('N' * 41, CORREO, PASSWORD_OK)
        self.assertFalse(es_valido)
        self.assertIn('40', mensaje)

    def test_email_invalido_es_invalido(self):
        es_valido, mensaje = validar_datos_registro(NOMBRE, 'no-es-correo', PASSWORD_OK)
        self.assertFalse(es_valido)
        self.assertIn('correo', mensaje.lower())


class BaseRegistro(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        if not db.session.get(Role, 0):
            db.session.add(Role(id=0, name='guest'))
            db.session.commit()

        # El limite de registro vive en un dict de modulo, compartido por todo
        # el proceso: sin limpiarlo, un caso contamination los siguientes.
        register_routes._INTENTOS_REGISTRO.clear()
        User.query.filter_by(email=CORREO).delete()
        db.session.commit()

    def tearDown(self):
        register_routes._INTENTOS_REGISTRO.clear()
        User.query.filter_by(email=CORREO).delete()
        db.session.remove()
        self.ctx.pop()


class TestAlta(BaseRegistro):
    def test_registro_exitoso(self):
        resultado = RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        self.assertTrue(resultado['success'], resultado['message'])
        self.assertIsNotNone(User.query.filter_by(email=CORREO).first())

    def test_nombre_y_correo_se_guardan_limpios(self):
        RegisterService.registrar_usuario('  ' + NOMBRE + '  ', '  ' + CORREO + ' ', PASSWORD_OK)
        usuario = User.query.filter_by(email=CORREO).first()
        self.assertIsNotNone(usuario, "Los espacios deben recortarse antes de guardar")
        self.assertEqual(usuario.name, NOMBRE)
        self.assertEqual(usuario.email, CORREO)

    def test_contrasena_se_guarda_hasheada(self):
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        usuario = User.query.filter_by(email=CORREO).first()
        self.assertNotEqual(usuario.password_hash, PASSWORD_OK)
        self.assertTrue(
            check_password_hash(usuario.password_hash, PASSWORD_OK),
            "El hash debe validar la contrasena original",
        )

    def test_correo_duplicado_es_rechazado(self):
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        resultado = RegisterService.registrar_usuario('Otro', CORREO, PASSWORD_OK)
        self.assertFalse(resultado['success'])
        self.assertEqual(User.query.filter_by(email=CORREO).count(), 1)

    def test_registro_invalido_no_crea_usuario(self):
        resultado = RegisterService.registrar_usuario(NOMBRE, CORREO, 'corta')
        self.assertFalse(resultado['success'])
        self.assertIsNone(User.query.filter_by(email=CORREO).first())


class TestAprobacion(BaseRegistro):
    """El alta debe quedar pendiente, no lista para entrar."""

    def test_nuevo_usuario_nace_inactivo(self):
        """Bug: se creaba con is_active=True y el invitado se saltaba el alta."""
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        usuario = User.query.filter_by(email=CORREO).first()
        self.assertFalse(
            usuario.is_active,
            "Un usuario recien registrado no debe quedar activo antes de aprobarse",
        )

    def test_nuevo_usuario_es_invitado(self):
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        usuario = User.query.filter_by(email=CORREO).first()
        self.assertEqual(usuario.role_id, 0, "role_id 0 = invitado, el estado de espera")

    def test_aparece_en_la_lista_de_pendientes(self):
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        pendientes = UserManagementRepository.get_pending_users()
        self.assertIn(CORREO, [u.email for u in pendientes])

    def test_invitado_pendiente_no_puede_autenticarse(self):
        """El bypass: is_active True + rol invitado permitia entrar sin aprobar."""
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        usuario, motivo = LoginService.autenticar(CORREO, PASSWORD_OK)
        self.assertNotEqual(
            motivo, "ok",
            "Un invitado pendiente no debe poder iniciar sesion",
        )
        self.assertEqual(motivo, "cuenta_desactivada")


class TestCheckEmail(BaseRegistro):
    def test_correo_existente_devuelve_json(self):
        RegisterService.registrar_usuario(NOMBRE, CORREO, PASSWORD_OK)
        respuesta = self.client.post(
            '/auth/check-email',
            json={'email': CORREO},
        )
        self.assertIn(respuesta.status_code, (200, 429))
        self.assertTrue(respuesta.is_json, "Debe responder JSON, no HTML")
        self.assertTrue(respuesta.get_json()['exists'])

    def test_correo_inexistente_devuelve_json(self):
        respuesta = self.client.post(
            '/auth/check-email',
            json={'email': 'nadie@prueba.test'},
        )
        self.assertIn(respuesta.status_code, (200, 429))
        self.assertTrue(respuesta.is_json)
        self.assertFalse(respuesta.get_json()['exists'])

    def test_correo_malformado_responde_400_json(self):
        """Bug: get_json() a ciegas lanzaba y devolvia 415 en HTML."""
        respuesta = self.client.post(
            '/auth/check-email',
            json={'email': 'esto-no-es-correo'},
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertTrue(respuesta.is_json)
        self.assertIn('error', respuesta.get_json())

    def test_cuerpo_no_json_no_revienta(self):
        respuesta = self.client.post(
            '/auth/check-email',
            data='no soy json',
            content_type='text/plain',
        )
        self.assertTrue(respuesta.is_json, "Nunca debe devolver HTML")
        self.assertIn(respuesta.status_code, (400, 415, 429))


class TestVistaRegistro(BaseRegistro):
    def test_get_pasa_las_reglas_para_el_checklist(self):
        respuesta = self.client.get('/auth/register')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertIn('data-password-min="6"', html)
        self.assertIn('data-password-max="12"', html)
        self.assertIn('data-password-require-upper="true"', html)
        self.assertIn('data-password-require-special="true"', html)

    def test_get_lista_las_tres_reglas(self):
        html = self.client.get('/auth/register').get_data(as_text=True)
        self.assertIn('data-rule="length"', html)
        self.assertIn('data-rule="upper"', html)
        self.assertIn('data-rule="special"', html)

    def test_get_carga_el_compartido_de_reglas(self):
        html = self.client.get('/auth/register').get_data(as_text=True)
        self.assertIn('js/security/password-rules.js', html)
        self.assertIn('css/security/password-rules.css', html)

    def test_no_referencia_el_css_inexistente(self):
        """auth_base.css no existe: era un 404 en cada carga de la pagina."""
        html = self.client.get('/auth/register').get_data(as_text=True)
        self.assertNotIn('/static/css/security/auth_base.css', html)
        self.assertIn('/static/css/security/auth.css', html)

    def test_post_invalido_muestra_el_mensaje_real(self):
        """Bug: la plantilla descartaba los avisos y no se veia ningun error."""
        respuesta = self.client.post(
            '/auth/register',
            data={'name': NOMBRE, 'email': CORREO, 'password': 'corta'},
        )
        html = respuesta.get_data(as_text=True)
        self.assertIn('entre 6 y 12', html)

    def test_post_valido_redirige_al_login(self):
        respuesta = self.client.post(
            '/auth/register',
            data={'name': NOMBRE, 'email': CORREO, 'password': PASSWORD_OK},
            follow_redirects=False,
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/auth/login', respuesta.headers['Location'])
        self.assertIsNotNone(User.query.filter_by(email=CORREO).first())

    def test_limite_de_registro_se_activa(self):
        for _ in range(5):
            self.client.post(
                '/auth/register',
                data={'name': NOMBRE, 'email': CORREO, 'password': 'mala'},
            )
        respuesta = self.client.post(
            '/auth/register',
            data={'name': NOMBRE, 'email': CORREO, 'password': PASSWORD_OK},
        )
        self.assertIn('Demasiados intentos', respuesta.get_data(as_text=True))
        self.assertIsNone(
            User.query.filter_by(email=CORREO).first(),
            "El limite debe frenar el alta, no solo avisar",
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
