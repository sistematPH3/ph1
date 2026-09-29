"""Pruebas del rediseño de "recuperar contraseña".

Motivo: diseño. La pantalla era un clon del inicio de sesión (mismas dos
columnas, mismo panel rojo, mismo input con divisor y mismo botón negro), y se
confundían entre sí. Estos tests fijan dos cosas:

1. El contrato funcional que token.js necesita: si falta un id, la pantalla
   deja de funcionar aunque se vea bien.
2. La separación respecto al login, para que nadie reintroduzca el clon.
"""
import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLANTILLA = os.path.join(RAIZ, 'app', 'templates', 'security', 'token_forgot.html')
PLANTILLA_RESET = os.path.join(RAIZ, 'app', 'templates', 'security', 'token_reset.html')
CSS_NUEVO = os.path.join(RAIZ, 'app', 'static', 'css', 'security', 'token_forgot.css')
CSS_RESET = os.path.join(RAIZ, 'app', 'static', 'css', 'security', 'token.css')

# Clases del login que hacían indistinguibles las dos pantallas.
CLASES_DEL_LOGIN = [
    'token-wrapper', 'login-wrapper', 'col-left', 'col-right',
    'right-content-wrapper', 'left-center-content', 'input-with-icon',
    'vertical-divider', 'form-input-auth', 'btn-final-negro',
    'agbalumo-subtitle-white', 'agbalumo-lead', 'pizza-slice-image',
    'group-icon', 'info-lead', 'info-text-peach', 'forget-pass-container',
    'forget-pass-peach', 'input-container-group', 'error-alert',
]


def _leer(ruta):
    with open(ruta, encoding='utf-8') as f:
        return f.read()


class TestContratoFuncional(unittest.TestCase):
    """token.js se apoya en estos ids: si faltan, la pantalla no funciona."""

    def setUp(self):
        self.html = _leer(PLANTILLA)

    def test_existen_los_ids_que_usa_token_js(self):
        for id_ in ('forgotForm', 'email', 'error-msg', 'mensaje'):
            with self.subTest(id=id_):
                self.assertIn(f'id="{id_}"', self.html)

    def test_el_input_de_correo_conserva_el_patron_del_backend(self):
        self.assertIn('data-email-pattern="{{ patron_email }}"', self.html)
        self.assertIn('type="email"', self.html)

    def test_el_formulario_sigue_siendo_gestionado_por_el_js(self):
        # El POST lo hace token.js con fetch: si se pone action/method a mano
        # se rompe el manejo de errores en JSON.
        form = re.search(r'<form[^>]*id="forgotForm"[^>]*>', self.html).group(0)
        self.assertIn('novalidate', form)
        self.assertNotIn('action=', form)
        self.assertNotIn('method=', form)

    def test_el_error_arranca_oculto_para_que_el_js_lo_muestre(self):
        # token.js hace errorMsg.style.display = 'block'.
        css = _leer(CSS_NUEVO)
        bloque = re.search(r'#error-msg\s*\{(.*?)\}', css, re.S).group(1)
        self.assertIn('display: none', bloque)

    def test_conserva_los_enlaces_de_navegacion(self):
        # La ruta real la resuelve url_for en tiempo de render.
        self.assertIn("url_for('security.login')", self.html)
        self.assertIn("url_for('security.register')", self.html)

    def test_mantiene_el_titulo_y_el_idioma(self):
        self.assertIn('lang="es"', self.html)
        self.assertIn('Recuperar Contraseña | Pizza Hut', self.html)


class TestSeparadoDelLogin(unittest.TestCase):
    """El objetivo del rediseño: que no se parezca al inicio de sesión."""

    def setUp(self):
        self.html = _leer(PLANTILLA)

    def test_no_reutiliza_las_clases_visuales_del_login(self):
        for clase in CLASES_DEL_LOGIN:
            with self.subTest(clase=clase):
                self.assertNotIn(f'class="{clase}', self.html)
                self.assertNotIn(f' {clase}"', self.html)

    def test_no_reutiliza_la_imagen_de_usuario_del_login(self):
        self.assertNotIn('icono_usuario.png', self.html)

    def test_usa_la_imagen_de_candado(self):
        self.assertIn('lock_icon.png', self.html)

    def test_no_tiene_la_estructura_de_dos_columnas(self):
        # El logo y el formulario ya no comparten wrappers de columna.
        for clase in ('col-left', 'col-right', 'token-wrapper'):
            with self.subTest(clase=clase):
                self.assertNotIn(clase, self.html)

    def test_el_rojo_es_acento_y_no_fondo_de_panel(self):
        # El panel rojo del login era lo más confundible: aquí el rojo aparece
        # como acento (barra superior y botón), no como fondo de media pagina.
        self.assertIn('.rf-card::before', _leer(CSS_NUEVO))
        self.assertNotIn('fondo_rojo', self.html)

    def test_incluye_el_indicador_de_pasos(self):
        self.assertIn('rf-steps', self.html)
        self.assertIn('is-active', self.html)

    def test_las_etiquetas_van_encima_del_input(self):
        # En login el input es una capsula con icono y divisor.
        self.assertIn('class="rf-label"', self.html)
        self.assertNotIn('field-icon', self.html)

    def test_el_boton_no_es_el_negro_del_login(self):
        self.assertIn('class="rf-btn"', self.html)
        self.assertNotIn('btn-final-negro', self.html)


class TestPaginaDeResetIntacta(unittest.TestCase):
    """token.css se comparte con la pantalla de nueva contraseña."""

    def test_la_recuperacion_ya_no_usa_token_css(self):
        html = _leer(PLANTILLA)
        self.assertIn('token_forgot.css', html)
        self.assertNotIn('token.css', html)

    def test_token_css_sigue_existiendo_para_la_pantalla_de_reset(self):
        self.assertTrue(os.path.isfile(CSS_RESET))


class TestCalidadDelCss(unittest.TestCase):
    def test_las_llaves_estan_balanceadas(self):
        css = _leer(CSS_NUEVO)
        self.assertEqual(css.count('{'), css.count('}'))

    def test_toda_variable_usada_esta_definida(self):
        css = _leer(CSS_NUEVO)
        usadas = {m for m in re.findall(r'var\((--rf-[a-z-]+)\)', css)}
        for variable in usadas:
            with self.subTest(variable=variable):
                self.assertIn(f'{variable}:', css)

    def test_todas_las_clases_del_css_se_usan_en_alguna_plantilla(self):
        # La hoja la comparten las dos pantallas del flujo (los dos pasos),
        # asi que una clase puede usarse solo en una de ellas.
        css = _leer(CSS_NUEVO)
        html = _leer(PLANTILLA) + _leer(PLANTILLA_RESET)
        clases = set(re.findall(r'\.(rf-[a-z-]+)', css))
        for clase in clases:
            with self.subTest(clase=clase):
                self.assertIn(clase, html)

    def test_respeta_preferencias_de_movimiento_reducido(self):
        self.assertIn('prefers-reduced-motion', _leer(CSS_NUEVO))

    def test_tiene_consultas_responsive(self):
        self.assertIn('@media (max-width', _leer(CSS_NUEVO))


class TestFlujoCoherente(unittest.TestCase):
    """Las dos pantallas son los pasos 1 y 2 del mismo flujo: se parecen."""

    def setUp(self):
        self.forgot = _leer(PLANTILLA)
        self.reset = _leer(PLANTILLA_RESET)

    def test_comparten_la_misma_hoja_de_estilos(self):
        self.assertIn('token_forgot.css', self.forgot)
        self.assertIn('token_forgot.css', self.reset)

    def test_ninguna_de_las_dos_usa_el_css_viejo_del_panel_rojo(self):
        for nombre, html in (('forgot', self.forgot), ('reset', self.reset)):
            with self.subTest(pantalla=nombre):
                self.assertNotIn('token.css', html)
                self.assertNotIn('on-red', html)

    def test_las_dos_muestran_el_indicador_de_pasos(self):
        for nombre, html in (('forgot', self.forgot), ('reset', self.reset)):
            with self.subTest(pantilla=nombre):
                self.assertIn('rf-steps', html)
                self.assertIn('Verifica tu correo', html)
                self.assertIn('Nueva contraseña', html)

    def test_paso_1_activo_al_recuperar_y_paso_2_activo_al_restablecer(self):
        # Recuperar: estas en el paso 1. Restablecer: ya lo completaste.
        self.assertIn('rf-step is-active', self.forgot)
        self.assertNotIn('is-done', self.forgot)
        self.assertIn('rf-step is-done', self.reset)
        self.assertIn('rf-step is-active', self.reset)

    def test_las_dos_conservan_el_contrato_que_usa_token_js(self):
        for nombre, html in (('forgot', self.forgot), ('reset', self.reset)):
            with self.subTest(pantalla=nombre):
                for id_ in ('error-msg', 'mensaje'):
                    self.assertIn(f'id="{id_}"', html)

    def test_el_formulario_de_reset_sigue_gestionado_por_el_js(self):
        form = re.search(r'<form[^>]*id="resetForm"[^>]*>', self.reset).group(0)
        self.assertIn('novalidate', form)
        self.assertNotIn('action=', form)
        self.assertNotIn('method=', form)
        for atributo in ('data-password-min', 'data-password-max',
                         'data-password-require-upper', 'data-password-require-special'):
            self.assertIn(atributo, self.reset)

    def test_la_pantalla_de_reset_usa_la_variante_clara_de_las_reglas(self):
        # .on-light es la variante de password-rules.css para fondo claro.
        self.assertIn('class="on-light"', self.reset)
        self.assertIn('password-rules.css', self.reset)

    def test_no_hay_logo_sobre_el_formulario(self):
        # Mariuska pidió quitarlo: el logo solo queda como favicon del navegador.
        # El icono del candado sí se mantiene, por eso se mira el logo y no
        # cualquier <img>.
        for nombre, html in (('forgot', self.forgot), ('reset', self.reset)):
            with self.subTest(pantalla=nombre):
                cuerpo = html.split('</head>')[-1]
                self.assertNotIn('rf-brand', html)
                self.assertNotIn('logo_ph.png', cuerpo)
                self.assertIn('<link rel="icon"', html)
                self.assertIn('lock_icon.png', html)

    def test_el_acepte_de_reset_sigue_ofreciendo_pedir_otro(self):
        self.assertIn("url_for('security.forgot_password')", self.reset)
        self.assertIn('rf-invalid', self.reset)


if __name__ == '__main__':
    unittest.main()
