# =============================================================================
# PRUEBAS DE LAS DESCARGAS DE RÁPIDO 2 (MÓDULO 8): PDF y Excel
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) construir_exportacion arma la cabecera de auditoría (período, sede(s),
#      moneda, generador, fecha) y las tablas de detalle.
#   2) El generador PDF produce bytes válidos (marca %PDF).
#   3) El generador Excel produce bytes válidos (archivo ZIP/OOXML).
#   4) La ruta /analytics/reportes/export entrega el archivo descargable.
#
# Uso (en la carpeta ph1):
#   .venv/Scripts/python -m unittest tests.analytics.test_export_reports -v
# =============================================================================

import os
import re
import unittest
from datetime import date, datetime
from decimal import Decimal

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
from app.models import (Location, Product, Purchase, PurchaseDetail, Role,
                        StatisticsSnapshot, Supplier, User)
from app.models.waste_model import Waste, WasteType
from app.models.statistics_model import SnapshotMetric, SnapshotPeriodType
from app.analytics.services import analysis_reports_service as svc
from app.reports.services import export_service
from app.reports.services.export_excel_generator import generar_excel
from app.reports.services.export_pdf_generator import generar_pdf


class ExportReportsTest(unittest.TestCase):

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

        self.central = Location(name="Almacén Central", state="Caracas",
                                is_active=True)
        self.central.id = 1  # el sistema identifica la Central por id 1
        self.sede = Location(name="Sede La Candelaria", state="Caracas",
                             is_active=True)
        self.sede.id = 2
        db.session.add_all([self.central, self.sede])
        db.session.flush()

        rol = Role(name="Administrator")
        db.session.add(rol)
        db.session.flush()
        self.admin = User(name="Mariuska Admin", email="export@ph.test",
                          password_hash="x", role_id=rol.id)
        db.session.add(self.admin)
        db.session.flush()

        db.session.add(StatisticsSnapshot(
            location_id=self.sede.id,
            metric=SnapshotMetric.PURCHASES,
            period_type=SnapshotPeriodType.MONTHLY,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            amount_usd=Decimal('1000.00'), amount_bs=Decimal('31000.00'),
            amount_eur=Decimal('850.00'), quantity=Decimal('500.00'),
            record_count=4, calculated_by_user_id=self.admin.id))
        proveedor = Supplier(name="Provee Real", tax_id="J-123")
        harina = Product(name="Harina Real", sku="H-EXP", unit_of_measure="KG")
        db.session.add_all([proveedor, harina])
        db.session.flush()
        compra = Purchase(supplier_id=proveedor.id,
                          purchase_date=datetime(2026, 9, 8),
                          total_amount=Decimal('1000.00'), currency='USD',
                          invoice_url='https://img/exp1.png',
                          status='COMPLETADO', user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=harina.id, lot_number='L-EXP',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        for tabla in reversed(db.metadata.sorted_tables):
            db.session.execute(tabla.delete())
        db.session.commit()
        self.ctx.pop()

    def _datos_exportacion(self, moneda='USD', location_id=None):
        if location_id is None:
            location_id = self.sede.id
        filtros = svc.ReportFilters(location_id=location_id,
                                    metric='PURCHASES',
                                    period_type='MONTHLY', moneda=moneda)
        return export_service.construir_exportacion(filtros, self.admin.id)

    def test_cabecera_de_auditoria_completa(self):
        datos = self._datos_exportacion()
        header = datos['header']
        self.assertEqual(header['sede'], 'Sede La Candelaria')
        self.assertEqual(header['periodo'], 'Septiembre 2026')
        self.assertEqual(header['moneda'], 'USD')
        self.assertEqual(header['generado_por'], 'Mariuska Admin')
        self.assertEqual(header['rango'], '01/09/2026 al 30/09/2026')

    def test_exportacion_reune_kpis_y_tablas(self):
        # Solo la Central compra: desde la Central el export reúne el KPI de
        # compras y la tabla por proveedor.
        datos = self._datos_exportacion(location_id=self.central.id)
        self.assertEqual(datos['kpis']['kpis']['compras']['actual'],
                         Decimal('1000.00'))
        tablas = datos['detalle_tablas']
        self.assertTrue(tablas)
        titulo, columnas, _ = tablas[0]
        self.assertEqual(titulo, 'Compras por proveedor')

    def test_export_sede_no_central_excluye_compras(self):
        # El export de una sede que no es la Central no muestra compras: el
        # KPI de compras desaparece y la métrica pasa a traslados.
        datos = self._datos_exportacion(location_id=self.sede.id)
        self.assertNotIn('compras', datos['kpis']['kpis'])
        self.assertEqual(datos['reporte']['filters']['metric'], 'TRANSFERS')
        self.assertEqual(datos['detalle_tablas'][0][0], 'Resumen de traslados')

    def test_export_waste_lista_cada_merma_real(self):
        tipo = WasteType(name='Vencido', code='VENCIDO', severity='MEDIA')
        db.session.add(tipo)
        db.session.flush()
        db.session.add(Waste(location_id=self.sede.id, waste_type_id=tipo.id,
                             date=datetime(2026, 9, 9), user_id=self.admin.id,
                             status='APROBADO',
                             total_quantity=Decimal('3.00'),
                             total_cost=Decimal('15.00'), currency='USD'))
        db.session.commit()
        filtros = svc.ReportFilters(location_id=self.sede.id, metric='WASTE',
                                    period_type='MONTHLY',
                                    period_start=date(2026, 9, 1),
                                    moneda='USD')
        datos = export_service.construir_exportacion(filtros, self.admin.id)
        titulo, columnas, filas = datos['detalle_tablas'][0]
        self.assertEqual(titulo, 'Mermas del período (cada registro real)')
        self.assertIn('Fecha', columnas)
        self.assertIn('Costo', columnas)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][2], 'Vencido')
        self.assertEqual(filas[0][4], '15,00')
        self.assertEqual(filas[0][5], 'USD')
        self.assertEqual(filas[0][6], '15,00 USD')

    def test_export_consolidado_incluye_por_concepto_y_por_sede(self):
        tipo = WasteType(name='Deteriorado', code='DETERIORADO',
                         severity='MEDIA')
        db.session.add(tipo)
        db.session.flush()
        db.session.add(Waste(location_id=self.sede.id, waste_type_id=tipo.id,
                             date=datetime(2026, 9, 10), user_id=self.admin.id,
                             status='APROBADO',
                             total_quantity=Decimal('3.00'),
                             total_cost=Decimal('15.00'), currency='USD'))
        db.session.commit()
        filtros = svc.ReportFilters(location_id=None,
                                    metric='CONSOLIDATED',
                                    period_type='MONTHLY',
                                    period_start=date(2026, 9, 1),
                                    moneda='USD')
        datos = export_service.construir_exportacion(filtros, self.admin.id)
        tabla_concepto, tabla_sede, tabla_moneda = datos['detalle_tablas']
        _, _, filas_concepto = tabla_concepto
        _, _, filas_sede = tabla_sede
        nombres_concepto = [fila[0] for fila in filas_concepto]
        self.assertIn('Mermas', nombres_concepto)
        self.assertEqual(nombres_concepto[-1], 'Resultado del período')
        self.assertEqual(filas_concepto[-1][1], '985,00')
        nombres_sede = [fila[0] for fila in filas_sede]
        self.assertIn('Sede La Candelaria', nombres_sede)
        self.assertIn('Compras Central', nombres_sede)
        titulo_moneda, columnas_moneda, filas_moneda = tabla_moneda
        self.assertEqual(titulo_moneda,
                         'Compras por moneda (en qué moneda se compra más)')
        self.assertIn('% del total', columnas_moneda)
        self.assertEqual([fila[0] for fila in filas_moneda], ['USD'])
        self.assertEqual(filas_moneda[0][1], '1.000,00')  # registrado en su moneda

    def test_pdf_genera_bytes_validos(self):
        datos = self._datos_exportacion(moneda='BS')
        buffer = generar_pdf(datos)
        contenido = buffer.getvalue()
        self.assertTrue(contenido.startswith(b'%PDF'))
        self.assertGreater(len(contenido), 1000)
        # Un PDF que un visor pueda abrir debe terminar en %%EOF y tener una
        # tabla xref con offsets dentro del rango del archivo.
        self.assertTrue(contenido.rstrip().endswith(b'%%EOF'),
                        'el PDF debe terminar en %%EOF')
        m = re.search(rb'startxref\s+(\d+)', contenido)
        self.assertIsNotNone(m, 'el PDF debe declarar startxref')
        xref_inicio = int(m.group(1))
        self.assertLess(xref_inicio, len(contenido))
        bloque_xref = contenido[xref_inicio:xref_inicio + 2000]
        entradas = re.findall(rb'(\d{10})\s+(\d{5})\s+n', bloque_xref)
        self.assertTrue(entradas, 'debe haber una tabla xref clásica')
        for offset, _gen in entradas[:40]:
            self.assertLess(int(offset), len(contenido),
                            'offsets de xref dentro del rango')

    def test_excel_genera_bytes_validos(self):
        datos = self._datos_exportacion()
        buffer = generar_excel(datos)
        contenido = buffer.getvalue()
        self.assertTrue(contenido.startswith(b'PK'))
        self.assertGreater(len(contenido), 1000)

    def test_ruta_export_entrega_pdf_descargable(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        respuesta = client.get(
            '/analytics/reportes/export?metric=PURCHASES'
            '&period_type=MONTHLY&moneda=USD&formato=pdf'
            f'&location_id={self.sede.id}')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.mimetype, 'application/pdf')
        self.assertTrue(respuesta.data.startswith(b'%PDF'))

    def test_ruta_export_formato_invalido_rechaza(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        respuesta = client.get('/analytics/reportes/export?formato=exe')
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(respuesta.get_json()['success'])


if __name__ == '__main__':
    unittest.main()