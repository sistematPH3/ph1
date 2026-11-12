"""Humo de las exportaciones de auditoría: blueprint + 6 endpoints + toolbar.

Verifica lo que ya está comprobado en vivo (url_map resuelve los 6 endpoints
y las plantillas incluyen el toolbar) pero de forma reproducible en CI.

Uso:
    .venv/bin/python -m unittest tests.analytics.test_audit_exports -v
"""

import os
import unittest

TEST_DATABASE_URL = os.environ.get(
    'TEST_DATABASE_URL',
    'postgresql://postgres:12345@localhost:5432/ph_test')
# La app lee DATABASE_URL al importarse: apuntarla a la base de pruebas antes
# de crearla para que este módulo nunca abra conexiones contra la base real.
os.environ['DATABASE_URL'] = TEST_DATABASE_URL

BLUEPRINT = 'audit_exports'

# (endpoint, descripción legible)
DESCARGAS = [
    ('descargar_accesos', 'Accesos'),
    ('descargar_usuarios', 'Usuarios'),
    ('descargar_compras', 'Compras'),
    ('descargar_movimientos', 'Movimientos'),
    ('descargar_mermas', 'Mermas'),
    ('descargar_inventario', 'Inventario'),
]

TOOLBAR = 'reports/audit_export_toolbar.html'
JS_STATIC = 'audit/audit_export.js'

TEMAS_AUDITORIA = [
    'security/login_audit.html',
    'security/audit_user.html',
    'security/audit_purchase.html',
    'waste/waste_audit.html',
    'logistics/movement_audit.html',
    'waste/auditinventory.html',
]


class AuditExportsSmokeTest(unittest.TestCase):
    """Los tres checks viven dentro de un TestCase para que unittest los ejecute."""

    @classmethod
    def setUpClass(cls):
        from app import create_app
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def test_blueprint_registrado_y_endpoints_resuelven(self):
        """Los 6 endpoints de descarga resuelven vía url_for dentro del app."""
        with self.app.test_request_context():
            from flask import url_for
            for endpoint, _nombre in DESCARGAS:
                url = url_for(f'{BLUEPRINT}.{endpoint}')
                self.assertTrue(url and url.startswith('/'),
                                f'{endpoint} sin URL')
                self.assertIn('export', url,
                              f'{endpoint} debe ser ruta de export')

    def test_bloque_cintillo_toolbar_se_incluye_en_todas_las_vistas(self):
        """Cada plantilla de auditoría incluye el toolbar de exportación."""
        for plantilla in TEMAS_AUDITORIA:
            ruta = os.path.join('app', 'templates', plantilla)
            with open(ruta, encoding='utf-8') as fh:
                contenido = fh.read()
            self.assertIn(TOOLBAR, contenido,
                          f'{plantilla}: falta {TOOLBAR}')

    def test_js_audit_export_se_incluye(self):
        """El script de exportación (formatos PDF/Excel) se carga en cada vista."""
        for plantilla in TEMAS_AUDITORIA:
            ruta = os.path.join('app', 'templates', plantilla)
            with open(ruta, encoding='utf-8') as fh:
                contenido = fh.read()
            self.assertIn(JS_STATIC, contenido,
                          f'{plantilla}: falta {JS_STATIC}')


if __name__ == '__main__':
    unittest.main()
