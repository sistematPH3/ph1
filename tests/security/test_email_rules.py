"""Pruebas de la regla compartida de correo.

Contexto del bug: el registro validaba el formato con un regex propio, pero
login y "recuperar contrasena" solo comprobaban que el texto incluyera '@'.
Eso dejaba pasar valores que el backend rechazaba ('sinarroba@', 'a@b'), y el
usuario se enteraba del error al enviar, no al escribir.

Ademas, ningun sitio exigia la palabra 'gmail': el unico indicio era el
placeholder "Ingrese su Gmail" del login. Este archivo fija esa decision:
cualquier dominio es valido, pero el arroba es obligatorio.
"""
import os
import re
import unittest

from app.security.requests.auth_validators import PATRON_EMAIL, validar_email

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS_RULES = os.path.join(RAIZ, 'app', 'static', 'js', 'security')
TEMPLATES = os.path.join(RAIZ, 'app', 'templates', 'security')

FORMULARIOS = ('register.js', 'token.js', 'login.js')

# (caso, esperado) - 'gmail' no es obligatorio; el '@' si.
CASOS = [
    ('karol123@galletita.com', True),   # el ejemplo de la peticion
    ('usuario@gmail.com', True),
    ('carlos@hotmail.com', True),
    ('ana@empresa.co.ve', True),
    ('correo@sub.dominio.org', True),
    ('sinarroba.com', False),           # sin arroba
    ('a@b', False),                     # dominio sin punto
    ('sinarroba@', False),              # arroba sin dominio
    ('@gmail.com', False),              # sin parte local
    ('dos@@x.com', False),
    ('con espacio@x.com', False),
    ('', False),
    (None, False),
]


def _leer(*partes):
    with open(os.path.join(*partes), encoding='utf-8') as f:
        return f.read()


class TestCorreoNoExigeGmail(unittest.TestCase):
    """El dominio es libre; lo unico obligatorio es el formato con arroba."""

    def test_cualquier_dominio_es_valido(self):
        for correo, _ in CASOS:
            with self.subTest(correo=correo):
                self.assertIsInstance(validar_email(correo), bool)

    def test_arroba_obligatorio(self):
        for correo in ['sinarroba.com', 'correo', 'gmail.com']:
            with self.subTest(correo=correo):
                self.assertFalse(validar_email(correo))

    def test_arroba_con_dominio_ajeno_a_gmail_es_valido(self):
        self.assertTrue(validar_email('karol123@galletita.com'))
        self.assertTrue(validar_email('carlos@hotmail.com'))
        self.assertTrue(validar_email('info@empresa.co.ve'))

    def test_el_patron_no_contains_gmail(self):
        self.assertNotIn('gmail', PATRON_EMAIL.pattern.lower())


class TestReglaCompartidaEnFrontend(unittest.TestCase):
    """Los tres formularios deben usar la misma regla, no una propia."""

    def test_existe_el_modulo_compartido(self):
        self.assertTrue(os.path.isfile(os.path.join(JS_RULES, 'email-rules.js')))

    def test_los_tres_formularios_usan_emailrules(self):
        for archivo in FORMULARIOS:
            with self.subTest(archivo=archivo):
                fuente = _leer(JS_RULES, archivo)
                self.assertIn('EmailRules', fuente,
                              f'{archivo} no usa la regla compartida')

    def test_ningun_formulario_usa_la_comprobacion_laxa_del_arroba(self):
        # 'includes("@")' es justo lo que dejaba pasar 'sinarroba@' y 'a@b'.
        for archivo in FORMULARIOS:
            with self.subTest(archivo=archivo):
                fuente = _leer(JS_RULES, archivo)
                self.assertNotIn("includes('@')", fuente)
                self.assertNotIn('includes("@")', fuente)

    def test_ningun_formulario_hardcodea_su_propio_regex_de_correo(self):
        for archivo in FORMULARIOS:
            with self.subTest(archivo=archivo):
                fuente = _leer(JS_RULES, archivo)
                # Debe quedar el comentario, no un /.../ suelto con '@'.
                sin_comentarios = re.sub(r'//.*|/\*.*?\*/', '', fuente, flags=re.S)
                self.assertIsNone(
                    re.search(r'=\s*/\^?\[\\?s@', sin_comentarios),
                    f'{archivo} sigue definiendo un regex de correo propio'
                )

    def test_el_modulo_usa_el_patron_por_defecto_del_backend(self):
        fuente = _leer(JS_RULES, 'email-rules.js')
        # La copia local debe seguir siendo equivalente a la del backend.
        por_defecto = re.search(r"POR_DEFECTO\s*=\s*'([^']+)'", fuente).group(1)
        esperado = PATRON_EMAIL.pattern.replace('\\', '\\\\')
        self.assertEqual(por_defecto, esperado)

    def test_el_js_ancora_el_patron(self):
        # Sin ^...$ el navegador aceptaria 'basura@x.com mas' (igual que el bug
        # de PATRON_EMAIL que se corrigio con fullmatch en el backend).
        fuente = _leer(JS_RULES, 'email-rules.js')
        self.assertIn("'^' + patron + '$'", fuente)


class TestPatronRenderizadoEnPlantillas(unittest.TestCase):
    """El backend debe inyectar su patron en las tres plantillas."""

    PLANTILLAS = ('register.html', 'login.html', 'token_forgot.html')

    # Cada plantilla carga un unico formulario, no los tres.
    CONSUMIDOR = {
        'register.html': 'register.js',
        'login.html': 'login.js',
        'token_forgot.html': 'token.js',
    }

    def test_las_tres_plantillas_inyectan_el_patron(self):
        for plantilla in self.PLANTILLAS:
            with self.subTest(plantilla=plantilla):
                fuente = _leer(TEMPLATES, plantilla)
                self.assertIn('data-email-pattern="{{ patron_email }}"', fuente)

    def test_las_tres_plantillas_cargan_el_modulo_compartido(self):
        for plantilla in self.PLANTILLAS:
            with self.subTest(plantilla=plantilla):
                fuente = _leer(TEMPLATES, plantilla)
                self.assertIn('js/security/email-rules.js', fuente)

    def test_el_modulo_se_carga_antes_del_formulario_que_lo_usa(self):
        for plantilla, consumidor in self.CONSUMIDOR.items():
            with self.subTest(plantilla=plantilla):
                fuente = _leer(TEMPLATES, plantilla)
                pos_reglas = fuente.index('js/security/email-rules.js')
                pos_form = fuente.index(f'js/security/{consumidor}')
                self.assertLess(pos_reglas, pos_form,
                                'EmailRules se cargaria despues de su consumidor')


class TestPlaceholderNoMencionaGmail(unittest.TestCase):
    """El placeholder era lo unico que sugeria que 'gmail' era obligatorio."""

    def test_login_ya_no_pide_ingresar_su_gmail(self):
        fuente = _leer(TEMPLATES, 'login.html')
        self.assertNotIn('Ingrese su Gmail', fuente)
        self.assertIn('Ingrese su correo', fuente)

    def test_el_mensaje_de_error_explica_el_arroba(self):
        fuente = _leer(TEMPLATES, 'login.html')
        self.assertIn('@', fuente.split('id="emailError"')[-1][:200])


class TestEquivalenciaBackendYFrontend(unittest.TestCase):
    """La regla que recibe el navegador debe dar el mismo veredicto."""

    def _regex_del_navegador(self):
        # Reconstruye lo que hace email-rules.js: new RegExp('^' + patron + '$')
        return re.compile('^' + PATRON_EMAIL.pattern + '$')

    def test_mismos_veredictos_que_el_backend(self):
        regex_js = self._regex_del_navegador()
        for correo, _ in CASOS:
            with self.subTest(correo=correo):
                if not isinstance(correo, str):
                    self.assertFalse(validar_email(correo))
                    continue
                bruto = correo
                esperado = validar_email(bruto)
                # El JS hace email.trim() antes de testear.
                self.assertEqual(bool(regex_js.match(bruto.strip())), esperado,
                                 f'el navegador discreparia del backend con {bruto!r}')

    def test_el_arroba_sigue_siendo_imprescindible_en_el_frontend(self):
        regex_js = self._regex_del_navegador()
        for correo in ['sinarroba.com', 'a@b', 'sinarroba@', '@x.com']:
            with self.subTest(correo=correo):
                self.assertIsNone(regex_js.match(correo))

    def test_dominio_libre_tambien_en_el_frontend(self):
        regex_js = self._regex_del_navegador()
        for correo in ['karol123@galletita.com', 'carlos@hotmail.com', 'x@tienda.io']:
            with self.subTest(correo=correo):
                self.assertIsNotNone(regex_js.match(correo))


if __name__ == '__main__':
    unittest.main()
