"""Pruebas de la recuperacion de contrasena.

Cada caso cubre un bug corregido:
- credenciales SMTP hardcodeadas y enlace a 127.0.0.1,
- UnboundLocalError (500) tras cambiar la contrasena,
- respuestas 415/400 en HTML que rompian el JS,
- enumeracion de correos, tokens multiples, tokens huerfanos,
- zona horaria inconsistente, columna 'used' muerta, sin rollback,
- validacion de email laxa y acoplamiento con 'dummy123'.
"""
import os
import unittest
from datetime import timedelta

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
from app.extensions import db as _db  # noqa: E402
from app.models import LoginAudit, PasswordRecovery, Role, User  # noqa: E402
from app.security.repositories import token_repositories as repo  # noqa: E402
from app.security.requests.auth_validators import (  # noqa: E402
    REGLAS_PASSWORD,
    validar_email,
    validar_password,
)
from app.security.requests.token_validators import (  # noqa: E402
    validar_nueva_password,
    validar_solicitud_recuperacion,
)
from app.security.services import token_services as svc  # noqa: E402


EMAIL_PRUEBA = 'recuperacion@prueba.test'


class BaseRecuperacion(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

        # El envio real no debe ocurrir en las pruebas.
        self._envio_real = svc.enviar_correo_recuperacion
        self._envio_ok = True
        svc.enviar_correo_recuperacion = self._enviar_falso

        # Los limites se prueban en un caso aparte.
        self._max_intentos = self.app.config['RECUPERACION_MAX_INTENTOS']
        self.app.config['RECUPERACION_MAX_INTENTOS'] = 100

        if not db.session.get(Role, 0):
            db.session.add(Role(id=0, name='guest'))
            db.session.commit()
        self.usuario = self._crear_usuario()

    def tearDown(self):
        svc.enviar_correo_recuperacion = self._envio_real
        self._limpiar()
        db.session.remove()
        self.ctx.pop()

    def _enviar_falso(self, email, token):
        return self._envio_ok

    def _crear_usuario(self, email=EMAIL_PRUEBA, activo=True):
        usuario = User(email=email, name='Prueba Rec',
                       password_hash='x', is_active=activo, role_id=0)
        db.session.add(usuario)
        db.session.commit()
        return usuario

    def _limpiar(self):
        db.session.rollback()
        LoginAudit.query.filter_by(user_id=self.usuario.id).delete(
            synchronize_session=False)
        PasswordRecovery.query.filter_by(user_id=self.usuario.id).delete(
            synchronize_session=False)
        db.session.flush()
        db.session.delete(self.usuario)
        db.session.commit()

    def _tokens(self):
        return PasswordRecovery.query.filter_by(
            user_id=self.usuario.id).order_by(PasswordRecovery.id).all()

    def _crear_token(self, usado=False, expira_en=timedelta(hours=1)):
        token = PasswordRecovery(
            user_id=self.usuario.id,
            token='tok-' + os.urandom(8).hex(),
            created_at=repo.ahora(),
            expires_at=repo.ahora() + expira_en,
            used=usado,
        )
        db.session.add(token)
        db.session.commit()
        return token


class TestValidadores(unittest.TestCase):
    """Formato de correo y reglas de contrasena."""

    def test_rechaza_correo_con_espacios_o_saltos(self):
        for email in ['a@b.com basura', 'a@b.com\nX: 1', 'a b@c.com',
                      'a@b..com', 'a@.com', '@b.com', 'a@b', 'a@@b.com', '']:
            with self.subTest(email=email):
                self.assertFalse(validar_email(email), email)

    def test_acepta_correo_normal(self):
        for email in ['a@b.com', 'sistemat3.ph@gmail.com', 'nombre.apellido@dominio.co.ve']:
            with self.subTest(email=email):
                self.assertTrue(validar_email(email), email)

    def test_password_cumple_reglas(self):
        es_valida, error = validar_password('Abcdef1!')
        self.assertTrue(es_valida)
        self.assertIsNone(error)

    def test_password_rechazada_por_cada_regla(self):
        for pwd, esperado in [
            ('Ab1!', 'entre 6 y 12'),
            ('Abcdefghijkl1!', 'entre 6 y 12'),
            ('abcdef1!', 'mayúscula'),
            ('Abcdefg1', 'especiales'),
        ]:
            with self.subTest(pwd=pwd):
                es_valida, error = validar_password(pwd)
                self.assertFalse(es_valida)
                self.assertIn(esperado, error)

    def test_validador_token_no_usa_dummy123(self):
        """Ya no se valida el email pasando una contrasena falsa."""
        import inspect
        fuente = inspect.getsource(validar_solicitud_recuperacion)
        self.assertNotIn('dummy123', fuente)
        self.assertNotIn('validar_credenciales_login', fuente)

    def test_validadores_de_token(self):
        self.assertEqual(validar_solicitud_recuperacion(None)[1],
                         'El correo es obligatorio.')
        self.assertEqual(validar_solicitud_recuperacion({'email': 'x'})[1],
                         'Por favor, ingrese un correo electrónico válido.')
        self.assertTrue(validar_solicitud_recuperacion({'email': 'a@b.com'})[0])
        self.assertEqual(validar_nueva_password({})[1], 'La contraseña es obligatoria.')
        self.assertTrue(validar_nueva_password({'new_password': 'Abcdef1!'})[0])


class TestEnlaceRecuperacion(BaseRecuperacion):
    """El enlace del correo no puede estar fijo en 127.0.0.1."""

    def test_enlace_usa_la_peticion_y_respeta_base_url(self):
        import app.security.services.token_services as servicio

        anterior = self.app.config['PUBLIC_BASE_URL']
        try:
            # Sin PUBLIC_BASE_URL el host sale de la peticion (nunca 127.0.0.1 fijo).
            self.app.config['PUBLIC_BASE_URL'] = ''
            with self.app.test_request_context(
                    '/auth/forgot-password', base_url='https://sistema.pizzahut.com'):
                enlace = servicio.construir_enlace_recuperacion('ABC123')
                self.assertEqual(
                    enlace, 'https://sistema.pizzahut.com/auth/reset-password/ABC123')

            # Con PUBLIC_BASE_URL se respeta ese host (produccion detras de proxy).
            self.app.config['PUBLIC_BASE_URL'] = 'https://mi-dominio.com/'
            with self.app.test_request_context(
                    '/auth/forgot-password', base_url='http://localhost:5000'):
                enlace = servicio.construir_enlace_recuperacion('ABC123')
                self.assertEqual(
                    enlace, 'https://mi-dominio.com/auth/reset-password/ABC123')
        finally:
            self.app.config['PUBLIC_BASE_URL'] = anterior

    def test_el_correo_no_lleva_una_url_fija(self):
        import inspect
        fuente = inspect.getsource(svc)
        # El enlace se armaba con un f-string pegado a 127.0.0.1.
        self.assertNotIn('f"http://127.0.0.1', fuente)
        self.assertNotIn("f'http://127.0.0.1", fuente)
        self.assertIn('url_for', fuente)


class TestSolicitud(BaseRecuperacion):
    """Generacion, invalidacion y limpieza de tokens."""

    def test_no_revela_si_el_correo_existe(self):
        """Mismo status y mismo cuerpo exista o no la cuenta."""
        r_existe = self.client.post('/auth/forgot-password',
                                    json={'email': EMAIL_PRUEBA})
        r_inexiste = self.client.post('/auth/forgot-password',
                                      json={'email': 'nadie-esta@prueba.test'})
        self.assertEqual(r_existe.status_code, 200)
        self.assertEqual(r_inexiste.status_code, 200)
        self.assertEqual(r_existe.get_json(), r_inexiste.get_json())

    def test_token_unico_invalida_los_anteriores(self):
        self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})
        self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})

        tokens = self._tokens()
        self.assertEqual(len(tokens), 2, 'deben crearse 2 filas')
        usados = [t.used for t in tokens]
        self.assertEqual(usados.count(False), 1, 'solo el mas reciente queda vigente')

    def test_token_anterior_ya_no_cambia_la_password(self):
        self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})
        primero = self._tokens()[0].token
        self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})
        segundo = self._tokens()[1].token

        r = self.client.post(f'/auth/reset-password/{segundo}',
                             json={'new_password': 'Nueva1!'})
        self.assertEqual(r.status_code, 200)

        r_viejo = self.client.post(f'/auth/reset-password/{primero}',
                                   json={'new_password': 'Vieja1!'})
        self.assertEqual(r_viejo.status_code, 400)

    def test_si_falla_el_correo_no_queda_token_huerfano(self):
        self._envio_ok = False
        r = self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(len(self._tokens()), 0,
                         'el token se elimina si el usuario nunca lo recibio')

    def test_usuario_inactivo_no_recibe_token(self):
        inactivo = self._crear_usuario('inactivo@prueba.test', activo=False)
        try:
            r = self.client.post('/auth/forgot-password',
                                 json={'email': 'inactivo@prueba.test'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(
                PasswordRecovery.query.filter_by(user_id=inactivo.id).count(), 0)
        finally:
            db.session.delete(inactivo)
            db.session.commit()

    def test_vigencia_unificada_sin_mezclar_utc_y_local(self):
        """created_at y expires_at deben usar la misma base de tiempo."""
        self.client.post('/auth/forgot-password', json={'email': EMAIL_PRUEBA})
        token = self._tokens()[0]
        delta = token.expires_at - token.created_at
        self.assertAlmostEqual(delta.total_seconds(),
                               self.app.config['RECUPERACION_VIGENCIA_HORAS'] * 3600,
                               delta=5)

    def test_purga_los_vencidos_y_usados(self):
        import app.security.services.token_services as servicio
        self._crear_token(expira_en=timedelta(hours=-2))
        self._crear_token(usado=True)
        self._crear_token()
        self.assertEqual(len(self._tokens()), 3)

        servicio.purgar_tokens_vencidos()
        restantes = self._tokens()
        self.assertEqual(len(restantes), 1, 'solo sobrevive el token vigente')
        self.assertFalse(restantes[0].used)


class TestCambioDePassword(BaseRecuperacion):
    """El bug del 500 y la consistencia del contrato."""

    def test_cambio_exitoso_audita_y_devuelve_200(self):
        token = self._crear_token()
        r = self.client.post(f'/auth/reset-password/{token.token}',
                             json={'new_password': 'Nueva1!'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('message', r.get_json())
        self.assertTrue(
            LoginAudit.query.filter_by(user_id=self.usuario.id,
                                       action='CAMBIO_CONTRASENA').count() == 1)

    def test_token_ya_usado_responde_400_y_no_500(self):
        """Antes: UnboundLocalError -> 500 con la clave cambiada."""
        token = self._crear_token(usado=True)
        r = self.client.post(f'/auth/reset-password/{token.token}',
                             json={'new_password': 'Nueva1!'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.get_json())

    def test_token_consumido_no_se_reutiliza(self):
        token = self._crear_token()
        self.client.post(f'/auth/reset-password/{token.token}',
                         json={'new_password': 'Nueva1!'})
        r = self.client.post(f'/auth/reset-password/{token.token}',
                             json={'new_password': 'Otra1!'})
        self.assertEqual(r.status_code, 400)

    def test_token_vencido_responde_400(self):
        token = self._crear_token(expira_en=timedelta(hours=-1))
        r = self.client.post(f'/auth/reset-password/{token.token}',
                             json={'new_password': 'Nueva1!'})
        self.assertEqual(r.status_code, 400)

    def test_password_invalida_responde_400(self):
        token = self._crear_token()
        for pwd in ['', 'corta1!', 'abc1234567', 'SinMayuscula1!', 'SinEspecial1']:
            with self.subTest(pwd=pwd):
                r = self.client.post(f'/auth/reset-password/{token.token}',
                                     json={'new_password': pwd})
                self.assertEqual(r.status_code, 400)
                self.assertIn('error', r.get_json())

    def test_si_la_auditoria_falla_el_usuario_igual_gana_200(self):
        """La password ya esta cambiada: un fallo de auditoria no debe ser 500."""
        import app.security.routes.token_routes as rutas

        token = self._crear_token()
        original = rutas._registrar_auditoria

        def auditoria_rota(user_id):
            raise RuntimeError('base de datos no disponible para auditar')

        rutas._registrar_auditoria = auditoria_rota
        try:
            r = self.client.post(f'/auth/reset-password/{token.token}',
                                 json={'new_password': 'Nueva1!'})
        finally:
            rutas._registrar_auditoria = original

        self.assertEqual(r.status_code, 200)
        self.assertIn('message', r.get_json())

    def test_consulta_de_vigencia_no_deja_sesion_rota(self):
        self.assertFalse(repo.consultar_vigencia_token('inexistente-xyz'))
        self.assertFalse(repo.consultar_vigencia_token('inexistente-xyz'))


class TestContratoHttp(BaseRecuperacion):
    """El JS siempre debe recibir JSON."""

    def test_post_sin_content_type_json_responde_json(self):
        """Antes devolvia 415 en HTML y el JS mostraba 'Error de conexion'."""
        r = self.client.post('/auth/forgot-password', data={'email': 'a@b.com'})
        self.assertNotEqual(r.status_code, 415)
        self.assertIn('application/json', r.content_type)
        self.assertIn('error', r.get_json())

    def test_post_con_json_malformado_responde_json(self):
        r = self.client.post('/auth/forgot-password', data='{roto',
                             content_type='application/json')
        self.assertIn(r.status_code, (200, 400))
        self.assertIn('application/json', r.content_type)

    def test_cuerpo_vacio_responde_json_con_error(self):
        r = self.client.post('/auth/forgot-password', json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.get_json())

    def test_get_reset_invalido_no_expone_el_formulario(self):
        r = self.client.get('/auth/reset-password/token-inexistente-xyz')
        self.assertEqual(r.status_code, 200)
        cuerpo = r.data.decode()
        self.assertIn('Enlace no válido', cuerpo)
        self.assertNotIn('id="resetForm"', cuerpo)
        self.assertNotIn('token.js', cuerpo)

    def test_get_reset_valido_expone_reglas_del_backend(self):
        token = self._crear_token()
        r = self.client.get(f'/auth/reset-password/{token.token}')
        cuerpo = r.data.decode()
        self.assertIn('id="resetForm"', cuerpo)
        self.assertIn(f'data-password-min="{REGLAS_PASSWORD["min_length"]}"', cuerpo)
        self.assertIn(f'data-password-max="{REGLAS_PASSWORD["max_length"]}"', cuerpo)
        self.assertIn('data-password-require-upper="true"', cuerpo)
        self.assertIn('data-password-require-special="true"', cuerpo)


class TestLimiteIntentos(BaseRecuperacion):
    """Freno al envio masivo de correos."""

    def test_forgot_password_se_bloquea_tras_varios_intentos(self):
        import app.security.routes.token_routes as rutas
        rutas._INTENTOS.clear()
        self.app.config['RECUPERACION_MAX_INTENTOS'] = 3

        estados = [self.client.post('/auth/forgot-password',
                                    json={'email': EMAIL_PRUEBA}).status_code
                   for _ in range(5)]
        self.assertIn(429, estados, f'sin bloqueo: {estados}')
        self.assertEqual(estados[-1], 429)
        rutas._INTENTOS.clear()

    def test_reset_se_bloquea_por_token(self):
        import app.security.routes.token_routes as rutas
        rutas._INTENTOS.clear()
        self.app.config['RECUPERACION_MAX_INTENTOS'] = 2
        token = self._crear_token()

        estados = [self.client.post(f'/auth/reset-password/{token.token}',
                                    json={'new_password': 'Nueva1!'}).status_code
                   for _ in range(4)]
        self.assertIn(429, estados, f'sin bloqueo: {estados}')
        rutas._INTENTOS.clear()


class TestConfigSegura(unittest.TestCase):
    def test_no_hay_secreto_publico_por_defecto(self):
        import inspect
        import app.config as cfg
        fuente = inspect.getsource(cfg)
        self.assertNotIn('una-clave-secreta-por-defecto', fuente)
        self.assertNotIn('xephkblwzhjownnz', fuente)

    def test_password_smtp_viene_del_entorno(self):
        import inspect
        import app.config as cfg
        fuente = inspect.getsource(cfg)
        self.assertIn("os.environ.get('MAIL_PASSWORD')", fuente)


if __name__ == '__main__':
    unittest.main(verbosity=2)
