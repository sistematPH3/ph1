"""Humo de las exportaciones de auditoría: blueprint + 6 endpoints + toolbar.

Verifica lo que ya está comprobado en vivo (url_map resuelve los 6 endpoints
y las plantillas incluyen el toolbar) pero de forma reproducible en CI.
"""

import os

os.environ.setdefault(
    'TEST_DATABASE_URL',
    'postgresql://postgres:12345@localhost:5432/ph_test')

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


def _crear_app():
    from app import create_app
    return create_app()


def test_blueprint_registrado_y_endpoints_resuelven():
    """Los 6 endpoints de descarga resuelven vía url_for dentro del app."""
    app = _crear_app()
    with app.test_request_context():
        from flask import url_for
        for endpoint, _nombre in DESCARGAS:
            url = url_for(f'{BLUEPRINT}.{endpoint}')
            assert url and url.startswith('/'), f'{endpoint} sin URL'
            assert 'export' in url, f'{endpoint} debe ser ruta de export'


def test_bloque_cintillo_toolbar_se_incluye_en_todas_las_vistas():
    """Cada plantilla de auditoría incluye el toolbar de exportación."""
    for plantilla in TEMAS_AUDITORIA:
        ruta = os.path.join('app', 'templates', plantilla)
        with open(ruta, encoding='utf-8') as fh:
            contenido = fh.read()
        assert TOOLBAR in contenido, f'{plantilla}: falta {TOOLBAR}'


def test_js_audit_export_se_incluye():
    """El script de exportación (formatos PDF/Excel) se carga en cada vista."""
    for plantilla in TEMAS_AUDITORIA:
        ruta = os.path.join('app', 'templates', plantilla)
        with open(ruta, encoding='utf-8') as fh:
            contenido = fh.read()
        assert JS_STATIC in contenido, f'{plantilla}: falta {JS_STATIC}'
