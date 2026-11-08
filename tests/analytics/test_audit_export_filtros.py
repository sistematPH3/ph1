# =============================================================================
# REGRESIÓN: LAS EXPORTACIONES DE AUDITORÍA RESPETAN LOS FILTROS DE PANTALLA
# -----------------------------------------------------------------------------
# El export (PDF/Excel) ahora toma los mismos filtros que ve el usuario en la
# pantalla: texto de búsqueda (q), hora exacta, sede (id/'global'/nombre) y
# severidad. Este archivo verifica el validador ampliado y el constructor de
# accesos (el más completo: q + hora + sede global/nombre/id + rango).
#
# Uso (en la carpeta ph1):
#   .venv/Scripts/python -m unittest tests.analytics.test_audit_export_filtros -v
# =============================================================================

import os
import unittest
from datetime import datetime, date

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _ensure_test_database_exists():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_ensure_test_database_exists()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db
from app.models import AuditLog, LoginAudit, Location, Role, User
from app.reports.requests.audit_export_validators import (
    validate_audit_export_params,
)
from app.reports.services import audit_export_service as svc


class AuditExportFiltrosTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self._sembrar()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # ---------------------------------------------------------- semilla ----
    def _sembrar(self):
        self.sede_a = Location(name="Sede La Candelaria", state="Caracas",
                               is_active=True)
        self.sede_b = Location(name="Sede Bello Monte", state="Caracas",
                               is_active=True)
        db.session.add_all([self.sede_a, self.sede_b])
        db.session.flush()

        self.rol_admin = Role(name="Administrator")
        self.rol_fin = Role(name="Finance")
        self.rol_ops = Role(name="Operaciones")
        db.session.add_all([self.rol_admin, self.rol_fin, self.rol_ops])
        db.session.flush()

        self.ana = User(name="Ana Admin", email="ana@ph.test",
                        password_hash="x", role_id=self.rol_admin.id)
        self.beto = User(name="Beto Ops", email="beto@ph.test",
                         password_hash="x", role_id=self.rol_ops.id)
        self.caro = User(name="Caro Fin", email="caro@ph.test",
                         password_hash="x", role_id=self.rol_fin.id)
        db.session.add_all([self.ana, self.beto, self.caro])
        db.session.flush()

        db.session.add_all([
            # Log A: sede A, 07:30 AM del 05/09/2026
            LoginAudit(user_id=self.ana.id, role_id=self.rol_admin.id,
                       location_id=self.sede_a.id, action="INICIO_SESION",
                       timestamp=datetime(2026, 9, 5, 7, 30)),
            # Log B: sede B, 02:00 PM del 05/09/2026 (02 PM en formato 12h)
            LoginAudit(user_id=self.beto.id, role_id=self.rol_ops.id,
                       location_id=self.sede_b.id, action="CERRAR_SESION",
                       timestamp=datetime(2026, 9, 5, 14, 0)),
            # Log C: sin sede (global), 07:30 AM del 10/08/2026
            LoginAudit(user_id=self.caro.id, role_id=self.rol_fin.id,
                       location_id=None, action="INICIO_SESION",
                       timestamp=datetime(2026, 8, 10, 7, 30)),
        ])
        db.session.commit()

    # ------------------------------------------------ usuario simulado -----
    def _admin(self):
        class _Falso:
            id = None
            is_admin = True
            is_finance = False
            locations = []
        return _Falso()

    def _exportar(self, **filtros):
        return svc.construir_documento('accesos', self._admin(), filtros)

    def _filas(self, doc):
        if not doc.get('detalle_tablas'):
            return []
        entrada = doc['detalle_tablas'][0]
        return entrada['filas'] if isinstance(entrada, dict) else entrada[2]

    def _columnas(self, doc):
        if not doc.get('detalle_tablas'):
            return []
        entrada = doc['detalle_tablas'][0]
        return entrada['columnas'] if isinstance(entrada, dict) else entrada[1]

    # ---------------------------------------------------- validador --------
    def test_validador_acepta_sede_numerica_global_y_nombre(self):
        val = validate_audit_export_params(
            {'sede': 'global', 'formato': 'excel'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['sede'], 'global')

        val = validate_audit_export_params({'sede': '3'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['sede'], 3)

        val = validate_audit_export_params({'sede': 'Sede Bello Monte'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['sede'], 'Sede Bello Monte')

        val = validate_audit_export_params({'sede': 'x' * 150})
        self.assertFalse(val['is_valid'])
        self.assertIn('sede', val['errors'])

    def test_validador_acepta_hora_hh_ampm(self):
        val = validate_audit_export_params({'hour': '07 AM'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['hour'], '07 AM')

        val = validate_audit_export_params({'hour': '27 PM'})
        self.assertFalse(val['is_valid'])
        self.assertIn('hour', val['errors'])

    def test_validador_mantiene_q_y_fechas(self):
        val = validate_audit_export_params(
            {'q': 'ana', 'desde': '2026-09-01', 'hasta': '2026-09-30'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['q'], 'ana')
        self.assertEqual(val['data']['desde'], date(2026, 9, 1))
        self.assertEqual(val['data']['hasta'], date(2026, 9, 30))

    def test_validador_acepta_todas_las_severidades_del_inventario(self):
        for sev in ('NORMAL', 'ALERTA', 'CRITICO', 'EDITADO', 'ANULADO',
                    'REABASTECIDO'):
            val = validate_audit_export_params({'severity': sev})
            self.assertTrue(val['is_valid'], sev)
            self.assertEqual(val['data']['severity'], sev)

        val = validate_audit_export_params({'severity': 'INEXISTENTE'})
        self.assertFalse(val['is_valid'])
        self.assertIn('severity', val['errors'])

    def test_validador_acepta_tab_ingresos_y_egresos(self):
        val = validate_audit_export_params({'tab': 'egresos'})
        self.assertTrue(val['is_valid'])
        self.assertEqual(val['data']['tab'], 'egresos')

        val = validate_audit_export_params({'tab': 'otro'})
        self.assertFalse(val['is_valid'])
        self.assertIn('tab', val['errors'])

    # ------------------------------------------------------- accesos ------
    def test_accesos_sin_filtros_trae_todo(self):
        doc = self._exportar()
        self.assertEqual(doc['header']['registros'], 3)
        self.assertEqual(len(self._filas(doc)), 3)

    def test_accesos_q_filtra_por_usuario_y_accion(self):
        doc = self._exportar(q='ana')
        self.assertEqual(doc['header']['registros'], 1)
        self.assertEqual(self._filas(doc)[0][2], 'Ana Admin')

        doc = self._exportar(q='CERRAR_SESION')
        self.assertEqual(doc['header']['registros'], 1)

    def test_accesos_hora_exacta(self):
        doc = self._exportar(hour='07 AM')
        self.assertEqual(doc['header']['registros'], 2)  # A (07:30) y C
        doc = self._exportar(hour='02 PM')
        self.assertEqual(doc['header']['registros'], 1)  # B (14:00)

    def test_accesos_sede_global(self):
        doc = self._exportar(sede='global')
        self.assertEqual(doc['header']['registros'], 1)
        self.assertEqual(self._filas(doc)[0][5], 'Global / Sin Sede')

    def test_accesos_sede_por_id_y_por_nombre(self):
        doc = self._exportar(sede=self.sede_b.id)
        self.assertEqual(doc['header']['registros'], 1)

        doc = self._exportar(sede='sede bello monte')
        self.assertEqual(doc['header']['registros'], 1)

        doc = self._exportar(sede='no existe')
        self.assertEqual(doc['header']['registros'], 0)

    def test_accesos_rango_un_dia(self):
        doc = self._exportar(desde=date(2026, 9, 5), hasta=date(2026, 9, 5))
        self.assertEqual(doc['header']['registros'], 2)
        sedes = [r[5] for r in self._filas(doc)]
        self.assertNotIn('Global / Sin Sede', sedes)

    # ------------------------------------------------------ inventario ----
    def _inventario_fixture(self, con_merma_pendiente=False):
        # El constructor de inventario considera admin a role_id == 1 (id fijo
        # del rol Administrador en el seed de producción); forzamos ese id.
        if db.session.get(Role, 1) is None:
            db.session.add(Role(id=1, name="Administrator"))
            db.session.flush()
        admin = User(name='Admin Inv', email='inv@ph.test', password_hash='x',
                     role_id=1)
        db.session.add(admin)
        db.session.flush()
        logs = [
            # Ingreso NORMAL (solo aparece si no hay filtro de severidad)
            AuditLog(user_id=admin.id, location_id=self.sede_a.id,
                     affected_table='purchases', action='COMPRA',
                     severity='NORMAL', timestamp=datetime(2026, 9, 5, 7, 30),
                     changed_data={'quantity_changed': 10,
                                   'product_name': 'Harina', 'notes': ''}),
            # Egreso ALERTA -> es el único que debe quedar con severity=ALERTA
            AuditLog(user_id=admin.id, location_id=self.sede_a.id,
                     affected_table='inventory', action='AJUSTE',
                     severity='ALERTA', timestamp=datetime(2026, 9, 5, 9, 0),
                     changed_data={'quantity_changed': -5,
                                   'product_name': 'Harina', 'notes': ''}),
        ]
        if con_merma_pendiente:
            # Merma en espera de aprobación: qty neutro, no descontó stock.
            logs.append(AuditLog(
                user_id=admin.id, location_id=self.sede_a.id,
                affected_table='wastes', action='MERMA',
                severity='ALERTA', timestamp=datetime(2026, 9, 5, 11, 0),
                changed_data={'event': 'CREADA', 'status': 'PENDIENTE',
                              'tipo_merma': 'Vencida'},
            ))
        db.session.add_all(logs)
        db.session.commit()
        return admin

    def _exportar_inv(self, admin, **filtros):
        return svc.construir_inventario(admin, filtros)

    def _titulo(self, entrada):
        return entrada['titulo'] if isinstance(entrada, dict) else entrada[0]

    def _filas_entrada(self, entrada):
        return entrada['filas'] if isinstance(entrada, dict) else entrada[2]

    def test_inventario_sin_filtros_exports_ingresos_y_egresos(self):
        admin = self._inventario_fixture()
        doc = self._exportar_inv(admin)
        self.assertEqual(doc['header']['registros'], 2)
        self.assertEqual(len(doc['detalle_tablas']), 2)
        self.assertEqual(self._titulo(doc['detalle_tablas'][0]),
                         'Ingresos de inventario')
        self.assertEqual(self._titulo(doc['detalle_tablas'][1]),
                         'Egresos de inventario')

    def test_inventario_severidad_filtra_y_muestra_ambas_secciones(self):
        admin = self._inventario_fixture()
        doc = self._exportar_inv(admin, severity='ALERTA')
        self.assertEqual(doc['header']['registros'], 1)
        # Ambas secciones presentes: Ingresos vacía (solo encabezados) y
        # Egresos con la fila AJUSTE.
        self.assertEqual(len(doc['detalle_tablas']), 2)
        self.assertEqual(self._titulo(doc['detalle_tablas'][0]),
                         'Ingresos de inventario')
        self.assertEqual(len(self._filas_entrada(doc['detalle_tablas'][0])), 0)
        self.assertEqual(self._titulo(doc['detalle_tablas'][1]),
                         'Egresos de inventario')
        self.assertEqual(len(self._filas_entrada(doc['detalle_tablas'][1])), 1)

        doc = self._exportar_inv(admin, severity='NORMAL')
        self.assertEqual(doc['header']['registros'], 1)
        self.assertEqual(len(doc['detalle_tablas']), 2)
        self.assertEqual(len(self._filas_entrada(doc['detalle_tablas'][0])), 1)
        self.assertEqual(self._titulo(doc['detalle_tablas'][0]),
                         'Ingresos de inventario')
        self.assertEqual(len(self._filas_entrada(doc['detalle_tablas'][1])), 0)

    def test_inventario_merma_en_espera_va_a_egresos(self):
        admin = self._inventario_fixture(con_merma_pendiente=True)
        doc = self._exportar_inv(admin)
        self.assertEqual(doc['header']['registros'], 3)

        ingresos, egresos = doc['detalle_tablas']
        self.assertEqual(self._titulo(ingresos), 'Ingresos de inventario')
        self.assertEqual(len(self._filas_entrada(ingresos)), 1)  # solo COMPRA
        self.assertEqual(self._titulo(egresos), 'Egresos de inventario')
        self.assertEqual(len(self._filas_entrada(egresos)), 2)  # AJUSTE + MERMA en espera

        acciones = [r[3] for r in self._filas_entrada(egresos)]
        self.assertIn('MERMA', acciones)

    def test_generadores_pdf_excel_soportan_seccion_vacia(self):
        from app.reports.services.audit_export_generators import (
            generar_excel_auditoria, generar_pdf_auditoria,
        )
        admin = self._inventario_fixture()
        doc = self._exportar_inv(admin, severity='ALERTA')  # Ingresos vacía
        pdf = generar_pdf_auditoria(doc['header'], doc['detalle_tablas'])
        xls = generar_excel_auditoria(doc['header'], doc['detalle_tablas'])
        self.assertGreater(len(pdf.getvalue()), 1000)
        self.assertGreater(len(xls.getvalue()), 1000)


if __name__ == '__main__':
    unittest.main()