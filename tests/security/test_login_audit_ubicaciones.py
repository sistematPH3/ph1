# =============================================================================
# REGRESIÓN: UBICACIONES EN AUDITORÍA DE ACCESOS
# -----------------------------------------------------------------------------
# Los accesos sin sede ya no se muestran como "Global / Sin Sede":
#   - Administradores / almacén general -> "Almacén Central"
#   - Invitados (rol Guest / role_id 0)  -> "Pantalla de Invitados"
#   - Usuarios de sedes regulares        -> nombre de su sede
# También se valida que el filtro de la pantalla ofrezca esas opciones y ya no
# exponga la opción global.
#
# Uso:
#   python -m unittest tests.security.test_login_audit_ubicaciones -v
# =============================================================================

import os
import unittest

from app.models import Location, LoginAudit, Role, User
from app.security.services.audit_location_service import (
    clave_filtro_ubicacion,
    es_acceso_administrador,
    es_acceso_invitado,
    etiqueta_ubicacion,
)

PLANTILLA = os.path.join('app', 'templates', 'security', 'login_audit.html')


def _acceso(role_id, role_name, location=None):
    rol = Role(id=role_id, name=role_name)
    usuario = User(name='Usuario Prueba', email='prueba@ph.test',
                   password_hash='x', role_id=role_id)
    log = LoginAudit(user_id=1, role_id=role_id, action='INICIO_SESION')
    log.role = rol
    log.user = usuario
    log.location = location
    return log


class LoginAuditUbicacionesTest(unittest.TestCase):

    def test_administrador_sin_sede_es_almacen_central(self):
        log = _acceso(1, 'Administrator')
        self.assertFalse(es_acceso_invitado(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Almacén Central')
        self.assertEqual(clave_filtro_ubicacion(log), 'central_warehouse')

    def test_invitado_sin_sede_es_pantalla_de_invitados(self):
        log = _acceso(0, 'Guest')
        self.assertTrue(es_acceso_invitado(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Pantalla de Invitados')
        self.assertEqual(clave_filtro_ubicacion(log), 'guest_screen')

    def test_invitado_reconocido_por_nombre_de_rol(self):
        log = _acceso(9, 'Guest')
        self.assertTrue(es_acceso_invitado(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Pantalla de Invitados')
        self.assertEqual(clave_filtro_ubicacion(log), 'guest_screen')

    def test_sede_regular_mantiene_su_nombre(self):
        sede = Location(id=7, name='Sede La Candelaria', state='Caracas')
        log = _acceso(3, 'Operaciones', location=sede)
        self.assertFalse(es_acceso_invitado(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Sede La Candelaria')
        self.assertEqual(clave_filtro_ubicacion(log), '7')

    def test_administrador_con_sede_fisica_sigue_siendo_almacen_central(self):
        """El admin opera en el Almacén Central lógico, no en la sede cargada."""
        sede = Location(id=7, name='Sede La Candelaria', state='Caracas')
        log = _acceso(1, 'Administrator', location=sede)
        self.assertTrue(es_acceso_administrador(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Almacén Central')
        self.assertEqual(clave_filtro_ubicacion(log), 'central_warehouse')

    def test_administrador_por_id_de_rol_sin_nombre_cargado(self):
        log = _acceso(1, None)
        self.assertTrue(es_acceso_administrador(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Almacén Central')
        self.assertEqual(clave_filtro_ubicacion(log), 'central_warehouse')

    def test_administrador_reconocido_por_el_usuario_del_acceso(self):
        rol = Role(id=1, name='Administrator')
        usuario = User(name='Admin Sesion', email='admin@ph.test',
                       password_hash='x', role_id=1)
        usuario.role = rol
        log = LoginAudit(user_id=1, action='INICIO_SESION')
        log.user = usuario
        self.assertTrue(es_acceso_administrador(log))
        self.assertEqual(etiqueta_ubicacion(log), 'Almacén Central')
        self.assertEqual(clave_filtro_ubicacion(log), 'central_warehouse')

    def test_sede_central_usa_la_clave_del_filtro_central(self):
        log = _acceso(3, 'Operaciones',
                      location=Location(id=1, name='Almacén Central',
                                        state='Caracas'))
        self.assertEqual(etiqueta_ubicacion(log), 'Almacén Central')
        self.assertEqual(clave_filtro_ubicacion(log), 'central_warehouse')

    def test_plantilla_ofrece_las_nuevas_opciones_y_elimina_global(self):
        with open(PLANTILLA, encoding='utf-8') as fh:
            contenido = fh.read()
        self.assertIn('value="central_warehouse">Almacén Central', contenido)
        self.assertIn('value="guest_screen">Pantalla de Invitados', contenido)
        self.assertNotIn('Global / Sin Sede', contenido)
        self.assertNotIn('value="global"', contenido)
        self.assertIn('data-location="{{ log|ubicacion_key }}"', contenido)
        # Las opciones fijas no dependen de la lista de sedes ni del rol.
        self.assertNotIn('current_user.is_finance', contenido)
        # La celda de ubicación se pinta con la etiqueta del servicio.
        self.assertIn('log|ubicacion_label', contenido)


if __name__ == '__main__':
    unittest.main()
