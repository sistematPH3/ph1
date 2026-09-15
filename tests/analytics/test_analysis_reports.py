# =============================================================================
# PRUEBAS DE LOS REPORTES DE ESTADÍSTICA DE RÁPIDO 2 (MÓDULO 8)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) El cálculo de períodos (semanal/mensual/trimestral/anual) y su anterior.
#   2) El objeto de datos del reporte: lee el "cajón" (statistics_snapshots),
#      calcula el comparativo con el período anterior (dif. y %).
#   3) Los KPIs (Compras, Cocina, Mermas, Traslados, Costo operativo).
#   4) El ranking entre sedes ordenado por la moneda base.
#   5) Los detalles sin valorizar: compras por proveedor, mermas por tipo,
#      resumen de traslados y conteo de consumo.
#   6) Los permisos: usuario sin sedes o con sede no permitida → error.
#   7) La API JSON y el validador de filtros.
#   8) Los gráficos: serie de evolución, desglose del reporte y ranking.
#
# Uso (en la carpeta ph1):
#   .venv/Scripts/python -m unittest tests.analytics.test_analysis_reports -v
# =============================================================================

import os
import unittest
from datetime import date, datetime, timedelta
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
from app.models import (Category, Inventory, Location,
                        Product, ProductType, Purchase, PurchaseDetail, Role,
                        StatisticsSnapshot, Supplier, ExchangeRateHistory, User)
from app.models.logistics_model import Movement, MovementDetail
from app.models.statistics_model import SnapshotMetric, SnapshotPeriodType
from app.models.waste_model import AuditLog, Waste, WasteDetail, WasteType
from app.analytics.requests.analysis_reports_validators import validate_report_filters
from app.analytics.repositories.analysis_reports_repository import (
    obtener_consumo_valorizado,
    obtener_mermas_detalle,
    obtener_mermas_resumen)
from app.analytics.services import analysis_reports_service as svc


def _redondo(moneda):
    return Decimal(moneda).quantize(Decimal('0.01'))


class AnalysisReportsTest(unittest.TestCase):

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
        self._sembrar_base()

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # ---------------------------------------------------------- semillas ----
    def _sembrar_base(self):
        self.central = Location(name="Almacén Central", state="Caracas",
                                is_active=True)
        self.central.id = 1  # el sistema identifica la Central por id 1
        self.sede_a = Location(name="Sede La Candelaria", state="Caracas",
                               is_active=True)
        self.sede_a.id = 2
        self.sede_b = Location(name="Sede Bello Monte", state="Caracas",
                               is_active=True)
        self.sede_b.id = 3
        self.vendido = WasteType(name="Vencido", code="VENCIDO", severity="MEDIA")
        self.categoria = Category(name="Contable")
        db.session.add_all([self.central, self.sede_a, self.sede_b,
                            self.vendido, self.categoria])
        db.session.flush()

        self.harina = Product(name="Harina", sku="HAR-800", unit_of_measure="KG",
                              product_type_id=None)
        self.jamon = Product(name="Jamón", sku="JAM-800", unit_of_measure="KG",
                             product_type_id=None)
        db.session.add_all([self.harina, self.jamon])
        db.session.flush()

        self.rol_admin = Role(name="Administrator")
        self.rol_finanzas = Role(name="Finance")
        db.session.add_all([self.rol_admin, self.rol_finanzas])
        db.session.flush()

        self.admin = User(name="Admin Test", email="admin@ph.test",
                          password_hash="x", role_id=self.rol_admin.id)
        self.financiero = User(name="Finanzas Test", email="fin@ph.test",
                               password_hash="x", role_id=self.rol_finanzas.id)
        db.session.add_all([self.admin, self.financiero])
        db.session.flush()
        self.financiero.locations.append(self.sede_a)

        self.proveedor = Supplier(name="Proveedor Uno", tax_id="J-0001")
        db.session.add(self.proveedor)

        self._sembrar_snapshots()
        db.session.commit()

    def _sembrar_snapshots(self):
        julio = date(2026, 7, 1)
        agosto = date(2026, 8, 1)
        setiembre = date(2026, 9, 1)

        def snap(loc, metric, inicio, usd, bs, eur, qty, registros):
            if inicio.month == 12:
                fin = date(inicio.year, 12, 31)
            else:
                fin = date(inicio.year, inicio.month + 1, 1) - timedelta(days=1)
            return StatisticsSnapshot(
                location_id=loc.id, metric=metric,
                period_type=SnapshotPeriodType.MONTHLY, period_start=inicio,
                period_end=fin,
                amount_usd=usd, amount_bs=bs, amount_eur=eur,
                quantity=qty, record_count=registros,
                calculated_by_user_id=self.admin.id,
            )

        db.session.add_all([
            # Setiembre: sede A compra 1000/31000/850, cocina 400, merma 100, envíos 200
            snap(self.sede_a, SnapshotMetric.PURCHASES, setiembre, 1000, 31000, 850, 500, 4),
            snap(self.sede_a, SnapshotMetric.KITCHEN_CONSUMPTION, setiembre, 400, 12400, 340, 300, 6),
            snap(self.sede_a, SnapshotMetric.WASTE, setiembre, 100, 3100, 85, 10, 2),
            snap(self.sede_a, SnapshotMetric.TRANSFERS, setiembre, 200, 6200, 170, 40, 1),
            # Agosto: sede A compró 800 (comparativo debe dar +25%)
            snap(self.sede_a, SnapshotMetric.PURCHASES, agosto, 800, 24800, 680, 400, 3),
            snap(self.sede_a, SnapshotMetric.KITCHEN_CONSUMPTION, agosto, 380, 11780, 323, 280, 5),
            snap(self.sede_a, SnapshotMetric.WASTE, agosto, 120, 3720, 102, 12, 2),
            snap(self.sede_a, SnapshotMetric.TRANSFERS, agosto, 150, 4650, 127, 30, 1),
            # Julio: referencia del anterior del anterior (no debe afectar)
            snap(self.sede_a, SnapshotMetric.PURCHASES, julio, 700, 21700, 595, 350, 3),
            # Sede B: apenas compras en setiembre (ranking: la sede A gasta más)
            snap(self.sede_b, SnapshotMetric.PURCHASES, setiembre, 600, 18600, 510, 300, 2),
            snap(self.sede_b, SnapshotMetric.WASTE, setiembre, 50, 1550, 42, 5, 1),
        ])

    # --------------------------------------------------------- períodos ----
    def test_periodo_mensual_calcula_rangos_y_anterior(self):
        marco = svc.calcular_periodo('MONTHLY', date(2026, 9, 15))
        self.assertEqual(marco['period_start'], date(2026, 9, 1))
        self.assertEqual(marco['period_end'], date(2026, 9, 30))
        self.assertEqual(marco['previous_start'], date(2026, 8, 1))
        self.assertEqual(marco['previous_end'], date(2026, 8, 31))

    def test_periodo_semanal_lunes_a_domingo(self):
        marco = svc.calcular_periodo('WEEKLY', date(2026, 9, 16))
        self.assertEqual(marco['period_start'], date(2026, 9, 14))
        self.assertEqual(marco['period_end'], date(2026, 9, 20))
        self.assertEqual(marco['previous_start'], date(2026, 9, 7))

    def test_periodo_trimestral_y_anual(self):
        marco = svc.calcular_periodo('QUARTERLY', date(2026, 9, 16))
        self.assertEqual(marco['period_start'], date(2026, 7, 1))
        self.assertEqual(marco['period_end'], date(2026, 9, 30))
        marco = svc.calcular_periodo('ANNUAL', date(2026, 9, 16))
        self.assertEqual(marco['period_start'], date(2026, 1, 1))
        self.assertEqual(marco['period_end'], date(2026, 12, 31))
        self.assertEqual(marco['previous_start'], date(2025, 1, 1))

    # ----------------------------------------------------- reporte --------
    def test_reporte_lee_del_cajon_y_compara_con_periodo_anterior(self):
        # Sede no central: no hay compras, PURCHASES se convierte en TRANSFERS y
        # se lee el cajón de traslados con comparativo contra el período anterior.
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        self.assertEqual(reporte['filters']['metric'], 'TRANSFERS')
        self.assertEqual(reporte['current']['amount_usd'], _redondo('200.00'))
        self.assertEqual(reporte['previous']['amount_usd'], _redondo('150.00'))
        comp = reporte['comparative']['USD']
        self.assertEqual(comp['diferencia'], _redondo('50.00'))
        self.assertEqual(comp['pct'], _redondo('33.33'))
        self.assertEqual(comp['direccion'], 'up')
        self.assertEqual(reporte['period']['label'], 'Septiembre 2026')

    def test_reporte_sin_snapshots_devuelve_ceros(self):
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_b.id,
                              metric='KITCHEN_CONSUMPTION',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        self.assertEqual(reporte['current']['amount_usd'], _redondo('0.00'))
        self.assertEqual(reporte['current']['record_count'], 0)

    def test_reporte_comparativo_en_las_tres_monedas(self):
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='WASTE',
                              period_type='MONTHLY', moneda='BS'),
            self.admin.id)
        comp_bs = reporte['comparative']['BS']
        self.assertEqual(comp_bs['actual'], _redondo('3100.00'))
        self.assertEqual(comp_bs['anterior'], _redondo('3720.00'))
        self.assertEqual(comp_bs['pct'], _redondo('-16.67'))
        self.assertEqual(comp_bs['direccion'], 'down')

    def test_reporte_empresa_completa_suma_sedes(self):
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=None, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        self.assertEqual(reporte['current']['amount_usd'],
                         _redondo('1600.00'))  # 1000 (A) + 600 (B)

    # --------------------------------------------------------- KPIs --------
    def test_kpis_usan_montos_reales_de_las_tablas(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/kpi1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-K1',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 9), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('3.00'),
                      total_cost=Decimal('15.00'), currency='USD')
        db.session.add(merma)
        db.session.commit()

        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY', None, 'USD')
        kpi = kpis['kpis']
        self.assertEqual(kpi['compras']['actual'], _redondo('1000.00'))
        self.assertEqual(kpi['consumo_cocina']['actual'], _redondo('0.00'))
        self.assertEqual(kpi['mermas']['actual'], _redondo('15.00'))
        self.assertEqual(kpi['traslados']['actual'], _redondo('0.00'))
        # 1000 − 0 − 15 − 0 = 985
        self.assertEqual(kpi['costo_operativo']['actual'], _redondo('985.00'))
        self.assertEqual(kpi['costo_operativo']['incluye_perdidas_traslado'],
                         _redondo('0.00'))

    def test_rango_desde_hasta_recorta_los_kpis_y_el_periodo(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/rango1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-R1',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 9), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('3.00'),
                      total_cost=Decimal('15.00'), currency='USD')
        db.session.add(merma)
        db.session.commit()

        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY', None, 'USD',
                                desde=date(2026, 9, 8), hasta=date(2026, 9, 8))
        self.assertEqual(kpis['kpis']['compras']['actual'], _redondo('1000.00'))
        self.assertEqual(kpis['kpis']['mermas']['actual'], _redondo('0.00'))
        self.assertEqual(kpis['period']['label'], 'Del 08/09/2026 al 08/09/2026')

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='WASTE',
                              period_type='MONTHLY',
                              desde=date(2026, 9, 1), hasta=date(2026, 9, 9)),
            self.admin.id)
        self.assertEqual(reporte['period']['start'], date(2026, 9, 1))
        self.assertEqual(reporte['period']['end'], date(2026, 9, 9))
        self.assertEqual(len(reporte['detail']['mermas']), 1)
        self.assertEqual(reporte['detail']['mermas'][0]['quantity'],
                         _redondo('3.00'))

    def test_fechas_disponibles_usa_las_tablas_reales(self):
        # Una compra completada y una merma aprobada definen las fechas marcables.
        db.session.add(Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/fechas1.png', status='COMPLETADO',
            user_id=self.admin.id))
        db.session.add(Waste(location_id=self.sede_a.id,
                             waste_type_id=self.vendido.id,
                             date=datetime(2026, 9, 9), user_id=self.admin.id,
                             status='APROBADO',
                             total_quantity=Decimal('3.00'),
                             total_cost=Decimal('15.00'), currency='USD'))
        db.session.commit()

        fechas = svc.obtener_fechas_disponibles([self.sede_a.id],
                                                'PURCHASES', 'MONTHLY')
        self.assertEqual(fechas, [date(2026, 9, 8)])
        waste_fechas = svc.obtener_fechas_disponibles([self.sede_a.id],
                                                      'WASTE', 'MONTHLY')
        self.assertEqual(waste_fechas, [date(2026, 9, 9)])
        # Sin registros de cocina para esa sede: no hay fechas marcables.
        sin_datos = svc.obtener_fechas_disponibles([self.sede_a.id],
                                                   'KITCHEN_CONSUMPTION',
                                                   'WEEKLY')
        self.assertEqual(sin_datos, [])
        # El consolidado une todas las fuentes.
        cons = svc.obtener_fechas_disponibles([self.sede_a.id],
                                              'CONSOLIDATED', 'MONTHLY')
        self.assertEqual(cons, [date(2026, 9, 8), date(2026, 9, 9)])

    def test_kpis_convierten_compras_a_la_moneda_seleccionada(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/kpi2.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-K2',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        db.session.add(ExchangeRateHistory(
            currency='USD', rate=Decimal('814.6908'), source='PRUEBA',
            timestamp=datetime(2026, 9, 1), user_id=self.admin.id))
        db.session.commit()

        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY', None, 'BS')
        self.assertEqual(kpis['kpis']['compras']['actual'],
                         _redondo('814690.80'))  # 1000 × 814.6908
        consolidado = svc.consolidado_financiero(
            [self.sede_a.id], datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59),
            'BS')
        self.assertEqual(consolidado['resultado'], _redondo('814690.80'))
        self.assertEqual(consolidado['por_concepto'][0]['monto'],
                         _redondo('814690.80'))

    def test_por_moneda_usa_la_tasa_del_dia_de_cada_compra(self):
        # Compra 1 (08/09, tasa del día 814,6908) y compra 2 (10/09, 827,7371).
        for dia, monto, tasa in ((8, '100.00', '814.6908'),
                                 (10, '200.00', '827.7371')):
            compra = Purchase(
                supplier_id=self.proveedor.id,
                purchase_date=datetime(2026, 9, dia),
                total_amount=Decimal(monto), currency='USD',
                exchange_rate=Decimal(tasa),
                invoice_url=f'https://img/mon{dia}.png', status='COMPLETADO',
                user_id=self.admin.id)
            db.session.add(compra)
            db.session.flush()
            db.session.add(PurchaseDetail(
                purchase_id=compra.id, product_id=self.harina.id,
                lot_number=f'L-{dia}', quantity=Decimal('1.00'),
                foreign_price=Decimal(monto),
                price_bs=(Decimal(monto) * Decimal(tasa)).quantize(
                    Decimal('0.01'))))
        db.session.commit()

        cons = svc.consolidado_financiero(
            [self.sede_a.id], datetime(2026, 9, 1),
            datetime(2026, 9, 30, 23, 59, 59), 'BS')
        # 100×814,6908 + 200×827,7371 = 81.469,08 + 165.547,42
        self.assertEqual(cons['por_concepto'][0]['monto'],
                         _redondo('247016.50'))
        self.assertEqual(cons['resultado'], _redondo('247016.50'))
        por_moneda = cons['por_moneda']
        self.assertEqual(por_moneda['total'], _redondo('247016.50'))
        self.assertEqual(len(por_moneda['filas']), 1)
        fila = por_moneda['filas'][0]
        self.assertEqual(fila['currency'], 'USD')
        self.assertEqual(fila['monto'], _redondo('300.00'))
        self.assertEqual(fila['compras'], 2)
        self.assertEqual(fila['equivalente'], _redondo('247016.50'))
        self.assertEqual(fila['pct'], _redondo('100.00'))

    # ------------------------------------------------------- ranking ------
    def test_ranking_ordena_por_monto_descendente_y_trae_variacion(self):
        ranking = svc.obtener_ranking([self.sede_a.id, self.sede_b.id],
                                      'PURCHASES', None, 'MONTHLY', 'USD')
        self.assertEqual(len(ranking), 2)
        self.assertEqual(ranking[0]['location_id'], self.sede_a.id)
        self.assertEqual(ranking[1]['location_id'], self.sede_b.id)
        self.assertEqual(ranking[0]['total_base'], _redondo('1000.00'))
        self.assertEqual(ranking[0]['anterior'], _redondo('800.00'))
        self.assertEqual(ranking[0]['pct'], _redondo('25.00'))
        self.assertIn(self.sede_a.name, ranking[0]['location_name'])

    # -------------------------------------------------------- detalle -----
    def test_detalle_compras_por_proveedor_agrupa_por_moneda(self):
        compra = Purchase(
            supplier_id=self.proveedor.id,
            purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('250.00'), currency='USD',
            invoice_url='https://img/factura1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.central.id, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        filas = reporte['detail']['por_proveedor']
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]['supplier_name'], 'Proveedor Uno')
        self.assertEqual(filas[0]['total_usd'], _redondo('250.00'))
        self.assertEqual(filas[0]['purchase_count'], 1)

    def test_detalle_mermas_lista_cada_registro_real(self):
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 10), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('3.00'),
                      total_cost=Decimal('15.00'), currency='USD')
        db.session.add(merma)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=merma.id, product_id=self.harina.id,
            waste_type_id=self.vendido.id, lot_number='L-1',
            quantity=Decimal('3.00'), unit_cost=Decimal('5.00'),
            subtotal_cost=Decimal('15.00'), status='APROBADO'))
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='WASTE',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        mermas = reporte['detail']['mermas']
        self.assertEqual(len(mermas), 1)
        self.assertEqual(mermas[0]['waste_type'], 'Vencido')
        self.assertEqual(mermas[0]['quantity'], _redondo('3.00'))
        self.assertEqual(mermas[0]['cost'], _redondo('15.00'))
        self.assertEqual(mermas[0]['currency'], 'USD')
        self.assertEqual(mermas[0]['sede'], 'Sede La Candelaria')

    def test_detalle_mermas_convierte_costo_a_la_moneda_seleccionada(self):
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 10), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('30.00'),
                      total_cost=Decimal('2100.00'), currency='USD')
        db.session.add(merma)
        db.session.add(ExchangeRateHistory(
            currency='USD', rate=Decimal('814.6908'), source='PRUEBA',
            timestamp=datetime(2026, 9, 1), user_id=self.admin.id))
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='WASTE',
                              period_type='MONTHLY', moneda='BS'),
            self.admin.id)
        merma = reporte['detail']['mermas'][0]
        self.assertEqual(merma['cost'], _redondo('1710850.68'))  # 2100 × 814.6908
        self.assertEqual(merma['currency'], 'BS')
        self.assertEqual(merma['cost_original'], _redondo('2100.00'))
        self.assertEqual(merma['origin_currency'], 'USD')

    def test_detalle_traslados_cuenta_enviados_recibidos_y_extravios(self):
        mov1 = Movement(type='DESPACHO', origin_location_id=self.central.id,
                        destination_location_id=self.sede_a.id,
                        date=datetime(2026, 9, 12), user_id=self.admin.id,
                        status='COMPLETADO')
        mov2 = Movement(type='DEVOLUCION', origin_location_id=self.sede_a.id,
                        destination_location_id=self.central.id,
                        date=datetime(2026, 9, 13), user_id=self.admin.id,
                        status='NOVEDAD_FALTANTE')
        db.session.add_all([mov1, mov2])
        db.session.flush()
        db.session.add(MovementDetail(movement_id=mov1.id,
                                      product_id=self.harina.id, lot_number='L-1',
                                      quantity=Decimal('10.00'),
                                      received_quantity=Decimal('10.00')))
        db.session.add(MovementDetail(movement_id=mov2.id,
                                      product_id=self.harina.id, lot_number='L-2',
                                      quantity=Decimal('10.00'),
                                      received_quantity=Decimal('5.00'),
                                      missing_quantity=Decimal('5.00')))
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='TRANSFERS',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        resumen = reporte['detail']
        # Sede no central: solo recibe; lo que sale es 'devueltos', jamás
        # 'enviados' (regla de negocio).
        self.assertEqual(resumen['recibidos'], 1)
        self.assertEqual(resumen['enviados'], 0)
        self.assertEqual(resumen['devueltos'], 1)
        self.assertEqual(resumen['tiene_enviados'], False)
        self.assertEqual(resumen['extravios_quantity'], _redondo('5.00'))
        self.assertEqual(resumen['por_estado']['NOVEDAD_FALTANTE'], 1)
        self.assertEqual(resumen['por_estado']['COMPLETADO'], 1)

        # Mercancía recibida por insumo / sede.
        recibido = resumen['recibido_por_insumo']
        self.assertIn('detalle', recibido)
        self.assertIn('top', recibido)
        filas = recibido['detalle']
        self.assertTrue(filas)
        # Lo recibido en la sede filtra el DEVOLUCION (que va hacia la Central),
        # así que solo queda el DESPACHO por 10.
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]['product_name'], 'Harina')
        self.assertEqual(filas[0]['quantity'], _redondo('10.00'))
        self.assertEqual(filas[0]['lots'], 1)
        self.assertEqual(recibido['top'][0]['quantity'], _redondo('10.00'))

    def test_recibido_por_insumo_rankea_por_cantidad_por_sede(self):
        # Central despacha dos productos; la sede recibe (recibidos) según la
        # cantidad realmente llegada. La devolución sale de la sede, no cuenta
        # como recibida aquí.
        mov1 = Movement(type='DESPACHO', origin_location_id=self.central.id,
                        destination_location_id=self.sede_a.id,
                        date=datetime(2026, 9, 12), user_id=self.admin.id,
                        status='COMPLETADO')
        mov2 = Movement(type='DESPACHO', origin_location_id=self.central.id,
                        destination_location_id=self.sede_a.id,
                        date=datetime(2026, 9, 12), user_id=self.admin.id,
                        status='COMPLETADO')
        db.session.add_all([mov1, mov2])
        db.session.flush()
        db.session.add(MovementDetail(movement_id=mov1.id,
                                      product_id=self.harina.id, lot_number='L-1',
                                      quantity=Decimal('50.00'),
                                      received_quantity=Decimal('50.00')))
        db.session.add(MovementDetail(movement_id=mov1.id,
                                      product_id=self.jamon.id, lot_number='J-1',
                                      quantity=Decimal('5.00'),
                                      received_quantity=Decimal('5.00')))
        db.session.add(MovementDetail(movement_id=mov2.id,
                                      product_id=self.harina.id, lot_number='L-2',
                                      quantity=Decimal('20.00'),
                                      received_quantity=Decimal('15.00'),
                                      missing_quantity=Decimal('5.00')))
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='TRANSFERS',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        recibido = reporte['detail']['recibido_por_insumo']
        filas = recibido['detalle']
        # Ranking descendente por cantidad: harina (65) antes que jamón (5).
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]['product_name'], 'Harina')
        self.assertEqual(filas[0]['quantity'], _redondo('65.00'))
        self.assertEqual(filas[0]['lots'], 2)
        self.assertEqual(filas[1]['product_name'], 'Jamón')
        self.assertEqual(filas[1]['quantity'], _redondo('5.00'))
        self.assertEqual([f['product_name'] for f in recibido['top']],
                         ['Harina', 'Jamón'])

    # ---------------------------------------------------- permisos ---------
    def test_usuario_sin_sedes_recibe_error(self):
        invitado = User(name="Sin Sedes", email="sin@ph.test",
                        password_hash="x", role_id=self.rol_finanzas.id)
        db.session.add(invitado)
        db.session.commit()
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=None, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            invitado.id)
        self.assertIn('error', reporte)

    def test_sede_no_permitida_recibe_error(self):
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_b.id, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.financiero.id)
        self.assertIn('error', reporte)

    def test_financiero_solo_ve_sus_sedes(self):
        sede_ids, error = svc.queda_reporte_usuario_autorizado(
            self.financiero.id, None)
        self.assertIsNone(error)
        self.assertEqual(sede_ids, [self.sede_a.id])

    # --------------------------------------------------- validadores ------
    def test_validador_acepta_filtros_por_defecto(self):
        resultado = validate_report_filters({'metric': '', 'period_type': '',
                                             'moneda': '', 'location_id': None,
                                             'period_start': None})
        self.assertTrue(resultado['is_valid'])
        self.assertEqual(resultado['data']['metric'], 'PURCHASES')
        self.assertEqual(resultado['data']['period_type'], 'MONTHLY')
        self.assertEqual(resultado['data']['moneda'], 'USD')

    def test_validador_acepta_desde_hasta(self):
        from datetime import date as _fecha
        from app.analytics.requests.analysis_reports_validators import (
            validate_report_filters,
        )
        resultado = validate_report_filters({
            'metric': 'WASTE', 'period_type': 'MONTHLY', 'moneda': 'USD',
            'period_start': None, 'location_id': None,
            'desde': '2026-09-01', 'hasta': '2026-09-08'})
        self.assertTrue(resultado['is_valid'])
        self.assertEqual(resultado['data']['desde'], _fecha(2026, 9, 1))
        self.assertEqual(resultado['data']['hasta'], _fecha(2026, 9, 8))

    def test_validador_rechaza_fecha_invalida_y_rango_invertido(self):
        from app.analytics.requests.analysis_reports_validators import (
            validate_report_filters,
        )
        base = {'metric': 'WASTE', 'period_type': 'MONTHLY', 'moneda': 'USD',
                'period_start': None, 'location_id': None}
        resultado = validate_report_filters({**base,
                                             'desde': '2026-99-99'})
        self.assertFalse(resultado['is_valid'])
        self.assertIn('desde', resultado['errors'])
        resultado = validate_report_filters({**base,
                                             'desde': '2026-09-08',
                                             'hasta': '2026-09-01'})
        self.assertFalse(resultado['is_valid'])
        self.assertIn('desde', resultado['errors'])

    def test_validador_rechaza_metric_periodo_moneda_fecha_invalidos(self):
        resultado = validate_report_filters({
            'metric': 'BASURA', 'period_type': 'DIARIO', 'moneda': 'YUAN',
            'location_id': 'abc', 'period_start': '2026-99-99'})
        self.assertFalse(resultado['is_valid'])
        self.assertIn('metric', resultado['errors'])
        self.assertIn('period_type', resultado['errors'])
        self.assertIn('moneda', resultado['errors'])
        self.assertIn('location_id', resultado['errors'])
        self.assertIn('period_start', resultado['errors'])

    # ------------------------------------------------------- API -----------
    def test_api_reportes_devuelve_cajon_y_comparativo(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        resp = client.get('/api/analytics/reportes?metric=PURCHASES'
                          '&period_type=MONTHLY&moneda=USD'
                          f'&location_id={self.sede_a.id}')
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.get_json()
        self.assertTrue(cuerpo['success'])
        self.assertEqual(cuerpo['report']['filters']['metric'], 'TRANSFERS')
        self.assertEqual(cuerpo['report']['comparative']['USD']['diferencia'],
                         _redondo('50.00'))

    def test_api_kpis_devuelve_las_cinco_tarjetas(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        resp = client.get('/api/analytics/kpis?period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)

    def test_pagina_reportes_renders_selector_kpis_y_ranking(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        resp = client.get(
            '/analytics/reportes?metric=PURCHASES&period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Reporte de Estadística', html)
        self.assertIn('name="metric"', html)
        self.assertIn('name="period_type"', html)
        self.assertIn(self.sede_a.name, html)
        self.assertIn(self.sede_b.name, html)
        self.assertIn('Costo operativo', html)
        self.assertIn('Ranking entre sedes', html)
        self.assertIn(self.sede_a.name, html)
        self.assertIn(self.sede_b.name, html)

    def test_pagina_reportes_financiero_ve_solo_sus_sedes(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get(
            '/analytics/reportes?metric=WASTE&period_type=MONTHLY&moneda=BS')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Reporte de Estadística', html)
        self.assertIn(self.sede_a.name, html)
        self.assertNotIn(self.sede_b.name, html)
        self.assertIn('Bolívares (Bs)', html)

    def test_pagina_reportes_finanzas_oculta_compras(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('1500.00'), currency='USD',
            invoice_url='https://img/fin2.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-F2',
            quantity=Decimal('10.00'), foreign_price=Decimal('150.00'),
            price_bs=Decimal('122203.64')))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get(
            '/analytics/reportes?metric=CONSOLIDATED&period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Consolidado financiero', html)
        self.assertNotIn('Compras por categoría contable', html)
        self.assertNotIn('Compras por moneda', html)
        self.assertNotIn('1.500,00', html)

    def test_pagina_reportes_admin_ve_compras(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('1500.00'), currency='USD',
            invoice_url='https://img/fin3.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-F3',
            quantity=Decimal('10.00'), foreign_price=Decimal('150.00'),
            price_bs=Decimal('122203.64')))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        resp = client.get(
            '/analytics/reportes?metric=CONSOLIDATED&period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Compras por categoría contable', html)
        self.assertIn('1.500,00', html)

    def test_pagina_reportes_admin_ve_traslados_hechos_desde_la_central(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/dashA.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-DA',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        entrada = Movement(type='DESPACHO', origin_location_id=self.central.id,
                           destination_location_id=self.sede_a.id,
                           date=datetime(2026, 9, 10), user_id=self.admin.id,
                           status='COMPLETADO')
        db.session.add(entrada)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=entrada.id, product_id=self.harina.id, lot_number='L-DA',
            quantity=Decimal('10.00'), received_quantity=Decimal('10.00')))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        resp = client.get('/analytics/reportes?metric=TRANSFERS'
                          '&period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Flujo direccional', html)
        self.assertIn('Enviados', html)
        self.assertIn(self.sede_a.name, html)

    def test_admin_al_filtrar_una_sede_no_central_ve_traslados_recibidos(self):
        """Un admin que filtra una sede común (no Central) narra los traslados
        desde ella: lo que llega es 'recibidos', no enviados."""
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 2),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/dirN.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-DN',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        entrada = Movement(type='DESPACHO', origin_location_id=self.central.id,
                           destination_location_id=self.sede_a.id,
                           date=datetime(2026, 9, 10), user_id=self.admin.id,
                           status='COMPLETADO')
        db.session.add(entrada)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=entrada.id, product_id=self.harina.id, lot_number='L-DN',
            quantity=Decimal('10.00'), received_quantity=Decimal('10.00')))
        db.session.commit()

        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY',
                                date(2026, 9, 15), 'USD',
                                incluir_compras=True)
        tr = kpis['kpis']['traslados']
        self.assertEqual(tr['label'], 'Traslados recibidos')
        self.assertEqual(tr['actual'], _redondo('1000.00'))
        self.assertEqual(tr['conteo'], 1)
        self.assertEqual(tr['quantity'], _redondo('10.00'))

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=self.sede_a.id, metric='TRANSFERS',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        direccional = reporte['detail']['direccional']
        self.assertEqual(direccional['recibidos']['conteo'], 1)
        self.assertEqual(direccional['devueltos']['conteo'], 0)

    def test_dashboard_finanzas_muestra_solo_traslados_recibidos(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get('/dashboard/finance')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Recibidos', html)
        self.assertIn('Traslados recibidos', html)
        self.assertNotIn('Flujo de traslados (enviados)', html)
        self.assertNotIn('Internos', html)

    def test_finance_dashboard_una_sola_sede_oculta_ranking(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/dash1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-D1',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get('/dashboard/finance')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Panel de Finanzas', html)
        self.assertIn('Indicadores del mes', html)
        self.assertNotIn('Ranking de compras entre sedes', html)
        self.assertIn('Traslados del mes', html)
        self.assertIn('Exportar PDF', html)
        self.assertNotIn(self.sede_b.name, html)
        # Finanzas que no gestiona la Central no ve compras
        self.assertNotIn('1.000,00', html)

    def test_finance_dashboard_varias_sedes_muestra_ranking(self):
        fin_multi = User(name="Finanzas Multi", email="finmulti@ph.test",
                         password_hash="x", role_id=self.rol_finanzas.id)
        fin_multi.locations.extend([self.sede_a, self.sede_b])
        db.session.add(fin_multi)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(fin_multi.id)
        resp = client.get('/dashboard/finance')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Ranking de traslados entre sedes', html)
        self.assertIn('reportes?metric=TRANSFERS', html)
        self.assertIn(self.sede_a.name, html)
        self.assertIn(self.sede_b.name, html)
        self.assertNotIn('Ranking de compras entre sedes', html)
        self.assertIn('Exportar PDF', html)

    def test_finance_dashboard_filtro_de_sede_acota_el_panel(self):
        fin_multi = User(name="Finanzas Filtro", email="finfiltro@ph.test",
                         password_hash="x", role_id=self.rol_finanzas.id)
        fin_multi.locations.extend([self.sede_a, self.sede_b])
        db.session.add(fin_multi)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(fin_multi.id)
        resp = client.get('/dashboard/finance?sede=%s' % self.sede_a.id)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        # La sede filtrada queda seleccionada; la otra sede no.
        self.assertIn('value="%s" selected' % self.sede_a.id, html)
        self.assertNotIn('value="%s" selected' % self.sede_b.id, html)
        self.assertIn('Ranking de traslados entre sedes', html)
        self.assertIn('Todas las sedes', html)

    def test_finance_dashboard_filtros_de_periodo_e_invalidos_no_rompen(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get('/dashboard/finance?periodo=2026-09-01')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Panel de Finanzas', html)
        self.assertIn('Indicadores del mes', html)
        # Sede no permitida: no debe romper; el panel queda con todas las sedes.
        resp2 = client.get('/dashboard/finance?sede=999999')
        self.assertEqual(resp2.status_code, 200)
        html2 = resp2.get_data(as_text=True)
        self.assertIn('Panel de Finanzas', html2)
        self.assertIn('value="" selected', html2)

    def test_finance_dashboard_barra_filtros_con_periodos_reales(self):
        # Una sola sede y sin snapshots del cajón: la barra de filtros aún se
        # renderiza y el período sale de los datos reales.
        db.session.add(AuditLog(
            affected_table='inventory', action='GASTO_COCINA',
            location_id=self.sede_a.id, user_id=self.admin.id,
            timestamp=datetime(2026, 9, 9, 12),
            changed_data={'product_id': self.harina.id, 'lot_number': 'N/A',
                          'quantity_changed': 1}))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        resp = client.get('/dashboard/finance')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Filtros', html)
        self.assertIn('Período', html)
        self.assertIn('value="2026-09-01"', html)
        self.assertIn('Septiembre 2026', html)

    def test_finance_dashboard_exporta_toda_la_informacion(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        html = client.get('/dashboard/finance').get_data(as_text=True)
        # El export baja el consolidado (compras, consumo, mermas y traslados),
        # no solo el detalle del traslado.
        self.assertIn("window.FIN_PANEL_METRIC = 'CONSOLIDATED'", html)
        self.assertIn('Evolución de egresos', html)
        self.assertIn('Resumen del período', html)
        resp = client.get(
            '/analytics/reportes/export?metric=CONSOLIDATED'
            '&period_type=MONTHLY&moneda=USD&formato=excel')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp.mimetype)

    def test_finanzas_sin_central_no_ve_compras_en_kpis_ni_consolidado(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('1500.00'), currency='USD',
            invoice_url='https://img/fin1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-F1',
            quantity=Decimal('10.00'), foreign_price=Decimal('150.00'),
            price_bs=Decimal('122203.64')))
        db.session.commit()
        self.assertFalse(svc.usuario_administra_central(self.financiero.id))
        self.assertTrue(svc.usuario_administra_central(self.admin.id))
        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY',
                                date(2026, 9, 15), 'USD',
                                incluir_compras=False)
        self.assertNotIn('compras', kpis['kpis'])
        self.assertEqual(kpis['kpis']['costo_operativo']['actual'], _redondo('0'))
        self.assertFalse(kpis['kpis']['costo_operativo']['medido_por_compras'])
        cons = svc.consolidado_financiero(
            [self.sede_a.id], date(2026, 9, 1), date(2026, 9, 30), 'USD',
            incluir_compras=False)
        self.assertEqual([c['concepto'] for c in cons['por_concepto']],
                         ['Consumo de cocina', 'Mermas', 'Pérdidas en traslados'])
        self.assertNotIn('Compras', [c['concepto'] for c in cons['por_concepto']])
        self.assertEqual(cons['por_categoria'], [])
        self.assertEqual(cons['por_moneda']['filas'], [])
        kpis_admin = svc.obtener_kpis([self.sede_a.id], 'MONTHLY',
                                      date(2026, 9, 15), 'USD',
                                      incluir_compras=True)
        self.assertEqual(kpis_admin['kpis']['compras']['actual'], _redondo('1500'))
        self.assertTrue(kpis_admin['kpis']['costo_operativo']['medido_por_compras'])

    def test_traslado_direccional_valora_recibidos_y_enviados_por_costo_real(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 2),
            total_amount=Decimal('2000.00'), currency='USD',
            invoice_url='https://img/dir1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-DIR',
            quantity=Decimal('20.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        entrada = Movement(type='DESPACHO', origin_location_id=self.central.id,
                           destination_location_id=self.sede_a.id,
                           date=datetime(2026, 9, 10), user_id=self.admin.id,
                           status='COMPLETADO')
        salida = Movement(type='DEVOLUCION', origin_location_id=self.sede_a.id,
                          destination_location_id=self.central.id,
                          date=datetime(2026, 9, 12), user_id=self.admin.id,
                          status='COMPLETADO')
        db.session.add_all([entrada, salida])
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=entrada.id, product_id=self.harina.id, lot_number='L-DIR',
            quantity=Decimal('10.00'), received_quantity=Decimal('10.00')))
        db.session.add(MovementDetail(
            movement_id=salida.id, product_id=self.harina.id, lot_number='L-DIR',
            quantity=Decimal('4.00'), received_quantity=Decimal('4.00')))
        db.session.commit()

        result = svc.obtener_traslados_direccional(
            [self.sede_a.id], datetime(2026, 9, 1),
            datetime(2026, 9, 30, 23, 59, 59), 'USD')
        self.assertEqual(result['recibidos']['conteo'], 1)
        self.assertEqual(result['recibidos']['quantity'], _redondo('10.00'))
        self.assertEqual(result['recibidos']['cost'], _redondo('1000.00'))
        self.assertEqual(result['enviados']['conteo'], 1)
        self.assertEqual(result['enviados']['quantity'], _redondo('4.00'))
        self.assertEqual(result['enviados']['cost'], _redondo('400.00'))
        self.assertEqual(result['internos']['conteo'], 0)
        self.assertEqual(result['total']['conteo'], 2)
        self.assertEqual(result['total']['cost'], _redondo('1400.00'))
        self.assertEqual(len(result['movimientos']), 2)

    def test_kpis_finanzas_flujo_principal_es_traslados_recibidos(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 2),
            total_amount=Decimal('1300.00'), currency='USD',
            invoice_url='https://img/dir2.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-KFL',
            quantity=Decimal('13.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        entrada = Movement(type='DESPACHO', origin_location_id=self.central.id,
                           destination_location_id=self.sede_a.id,
                           date=datetime(2026, 9, 10), user_id=self.admin.id,
                           status='COMPLETADO')
        salida = Movement(type='DEVOLUCION', origin_location_id=self.sede_a.id,
                          destination_location_id=self.central.id,
                          date=datetime(2026, 9, 12), user_id=self.admin.id,
                          status='COMPLETADO')
        db.session.add_all([entrada, salida])
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=entrada.id, product_id=self.harina.id, lot_number='L-KFL',
            quantity=Decimal('10.00'), received_quantity=Decimal('10.00')))
        db.session.add(MovementDetail(
            movement_id=salida.id, product_id=self.harina.id, lot_number='L-KFL',
            quantity=Decimal('3.00'), received_quantity=Decimal('3.00')))
        db.session.commit()

        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY',
                                date(2026, 9, 15), 'USD',
                                incluir_compras=False)
        self.assertNotIn('compras', kpis['kpis'])
        tr = kpis['kpis']['traslados']
        self.assertEqual(tr['label'], 'Traslados recibidos')
        self.assertEqual(tr['actual'], _redondo('1000.00'))
        self.assertEqual(tr['conteo'], 1)
        self.assertEqual(tr['quantity'], _redondo('10.00'))
        self.assertEqual(kpis['kpis']['costo_operativo']['medido_por_compras'],
                         False)

        kpis_admin = svc.obtener_kpis([self.central.id], 'MONTHLY',
                                      date(2026, 9, 15), 'USD',
                                      incluir_compras=True)
        tr_admin = kpis_admin['kpis']['traslados']
        self.assertEqual(tr_admin['label'], 'Traslados enviados')
        self.assertEqual(tr_admin['actual'], _redondo('1000.00'))
        self.assertEqual(tr_admin['conteo'], 1)

    def test_admin_orienta_los_traslados_desde_la_central_con_todas_sus_sedes(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 2),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/dir3.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-DA',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        entrada = Movement(type='DESPACHO', origin_location_id=self.central.id,
                           destination_location_id=self.sede_a.id,
                           date=datetime(2026, 9, 10), user_id=self.admin.id,
                           status='COMPLETADO')
        db.session.add(entrada)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=entrada.id, product_id=self.harina.id, lot_number='L-DA',
            quantity=Decimal('10.00'), received_quantity=Decimal('10.00')))
        db.session.commit()

        todos = [self.central.id, self.sede_a.id]
        kpis = svc.obtener_kpis(todos, 'MONTHLY', date(2026, 9, 15), 'USD',
                                incluir_compras=True)
        tr = kpis['kpis']['traslados']
        self.assertEqual(tr['label'], 'Traslados enviados')
        self.assertEqual(tr['actual'], _redondo('1000.00'))
        self.assertEqual(tr['conteo'], 1)
        self.assertEqual(tr['quantity'], _redondo('10.00'))

        directo = svc.obtener_traslados_direccional(
            todos, datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59),
            'USD', orientacion_id=self.central.id)
        self.assertEqual(directo['enviados']['conteo'], 1)
        self.assertEqual(directo['enviados']['cost'], _redondo('1000.00'))
        self.assertEqual(directo['recibidos']['conteo'], 0)
        self.assertEqual(directo['internos']['conteo'], 0)

    def test_kpis_y_ranking_alinean_una_fecha_al_periodo(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 15),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/dash2.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-D2',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        db.session.commit()
        kpis = svc.obtener_kpis([self.sede_a.id], 'MONTHLY',
                                date(2026, 9, 15), 'USD')
        self.assertEqual(kpis['kpis']['compras']['actual'], _redondo('1000'))
        ranking = svc.obtener_ranking([self.sede_a.id], 'PURCHASES',
                                      date(2026, 9, 15), 'MONTHLY', 'USD')
        self.assertEqual(ranking[0]['location_name'], self.sede_a.name)
        self.assertEqual(ranking[0]['total_base'], _redondo('1000'))

    def test_reporte_consolidado_detalla_conceptos_y_resultado(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('1000.00'), currency='USD',
            invoice_url='https://img/cons1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-C1',
            quantity=Decimal('10.00'), foreign_price=Decimal('100.00'),
            price_bs=Decimal('81469.09')))
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 6), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('3.00'),
                      total_cost=Decimal('15.00'), currency='USD')
        db.session.add(merma)
        db.session.commit()

        filtros = svc.ReportFilters(metric='CONSOLIDATED',
                                    period_type='MONTHLY')
        reporte = svc.construir_reporte(filtros, self.admin.id)
        self.assertNotIn('error', reporte)
        cons = reporte['detail']['consolidado']
        conceptos = [c['concepto'] for c in cons['por_concepto']]
        self.assertEqual(conceptos,
                         ['Compras', 'Consumo de cocina', 'Mermas',
                          'Pérdidas en traslados'])
        # 1000 − 0 − 15 − 0 = 985 USD exactos
        self.assertEqual(reporte['current']['amount_usd'], _redondo('985.00'))
        self.assertEqual(cons['resultado'], _redondo('985.00'))
        sedes = [s['sede'] for s in cons['por_sede']]
        self.assertIn('Compras Central', sedes)
        self.assertIn('Sede La Candelaria', sedes)
        categorias = [c['category'] for c in cons['por_categoria']]
        self.assertIn('Sin categoría', categorias)

    def test_pagina_reportes_consolidado_renders(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        resp = client.get('/analytics/reportes?metric=CONSOLIDATED&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Consolidado financiero', html)
        self.assertIn('Resultado del período', html)

    # ---------------------------------------------------- gráficos --------
    def test_evolucion_alinea_periodos_y_montos_del_cajon(self):
        evol = svc.obtener_evolucion([self.sede_a.id], 'PURCHASES', 'MONTHLY',
                                     date(2026, 9, 15), 'USD', limite=3)
        etiquetas = [p['label'] for p in evol]
        self.assertEqual(etiquetas,
                         ['Julio 2026', 'Agosto 2026', 'Septiembre 2026'])
        self.assertEqual(evol[-1]['value'], _redondo('1000.00'))
        self.assertEqual(evol[-2]['value'], _redondo('800.00'))

    def test_evolucion_traslados_grafica_conteo_de_registros(self):
        evol = svc.obtener_evolucion([self.sede_a.id], 'TRANSFERS', 'MONTHLY',
                                     date(2026, 9, 15), 'USD', limite=2)
        self.assertEqual([p['value'] for p in evol],
                         [_redondo('1.00'), _redondo('1.00')])

    def test_evolucion_suma_la_empresa_completa(self):
        evol = svc.obtener_evolucion([self.central.id, self.sede_a.id,
                                      self.sede_b.id],
                                     'PURCHASES', 'MONTHLY',
                                     None, 'USD', limite=1)
        self.assertEqual(evol[-1]['value'], _redondo('1600.00'))

    # ------------------------------------------------- datos reales (sin cajón) ----
    def _compra_real(self, fecha, lote, cantidad, precio, total):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=fecha,
            total_amount=Decimal(str(total)), currency='USD',
            invoice_url='https://img/evol1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number=lote,
            quantity=Decimal(str(cantidad)), foreign_price=Decimal(str(precio)),
            price_bs=Decimal('81469.09')))
        return compra

    def _merma_real(self, loc, costo, dia=9):
        db.session.add(Waste(
            location_id=loc.id, waste_type_id=self.vendido.id,
            date=datetime(2026, 9, dia), user_id=self.admin.id,
            status='APROBADO', total_quantity=Decimal('3.00'),
            total_cost=Decimal(str(costo)), currency='USD'))

    def test_evolucion_usa_datos_reales_cuando_el_cajon_esta_vacio(self):
        db.session.query(StatisticsSnapshot).delete()
        self._compra_real(datetime(2026, 9, 8), 'L-E1', 10, 100, 1000)
        self._compra_real(datetime(2026, 8, 5), 'L-E2', 5, 60, 300)
        db.session.commit()

        evol = svc.obtener_evolucion([self.central.id], 'PURCHASES', 'MONTHLY',
                                     None, 'USD', limite=6)
        self.assertEqual([p['label'] for p in evol],
                         ['Agosto 2026', 'Septiembre 2026'])
        self.assertEqual(evol[-1]['value'], _redondo('1000.00'))
        self.assertEqual(evol[-2]['value'], _redondo('300.00'))

        anclas = svc.obtener_anclas_selector(
            [self.central.id], 'PURCHASES', 'MONTHLY')
        self.assertEqual(anclas, [date(2026, 9, 1), date(2026, 8, 1)])

    def test_reporte_total_real_sin_cajon(self):
        db.session.query(StatisticsSnapshot).delete()
        self._compra_real(datetime(2026, 9, 8), 'L-R1', 10, 100, 1000)
        self._compra_real(datetime(2026, 8, 5), 'L-R2', 5, 60, 300)
        db.session.commit()

        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=None, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        self.assertEqual(reporte['current']['amount_usd'], _redondo('1000.00'))
        self.assertEqual(reporte['current']['record_count'], 1)
        self.assertEqual(reporte['previous']['amount_usd'], _redondo('300.00'))
        self.assertEqual(reporte['period']['label'], 'Septiembre 2026')

    def test_ranking_usa_datos_reales_sin_cajon(self):
        db.session.query(StatisticsSnapshot).delete()
        self._merma_real(self.sede_a, 15)
        self._merma_real(self.sede_b, 10)
        db.session.commit()

        ranking = svc.obtener_ranking([self.sede_a.id, self.sede_b.id],
                                      'WASTE', None, 'MONTHLY', 'USD')
        self.assertEqual(ranking[0]['location_name'], self.sede_a.name)
        self.assertEqual(ranking[0]['amount_usd'], _redondo('15.00'))
        self.assertEqual(ranking[1]['location_name'], self.sede_b.name)
        self.assertEqual(ranking[1]['amount_usd'], _redondo('10.00'))
        # Sin comparativo real en agosto → variación nula, no rompe.
        self.assertEqual(ranking[0]['pct'], None)

    def test_construir_graficos_incluye_evolucion_detalle_y_ranking(self):
        db.session.add(Purchase(
            supplier_id=self.proveedor.id,
            purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('250.00'), currency='USD',
            invoice_url='https://img/factura1.png', status='COMPLETADO',
            user_id=self.admin.id))
        db.session.commit()
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=None, metric='PURCHASES',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        ranking = svc.obtener_ranking([self.sede_a.id, self.sede_b.id],
                                      'PURCHASES', None, 'MONTHLY', 'USD')
        graficos = svc.construir_graficos(reporte, ranking, 'USD')
        self.assertEqual(len(graficos['evolucion']), 6)
        self.assertEqual(graficos['detalle']['titulo'], 'Compras por proveedor')
        self.assertEqual(graficos['metric'], 'PURCHASES')
        self.assertEqual(graficos['ranking']['labels'],
                         [self.sede_a.name, self.sede_b.name])
        self.assertEqual(graficos['gasto']['labels'][-1], 'Septiembre 2026')

    def test_pagina_reportes_incluye_graficos_y_cdn(self):
        compra = Purchase(
            supplier_id=self.proveedor.id,
            purchase_date=datetime(2026, 9, 5),
            total_amount=Decimal('250.00'), currency='USD',
            invoice_url='https://img/factura1.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-1',
            quantity=Decimal('5.00'), foreign_price=Decimal('50.00'),
            price_bs=Decimal('40734.54')))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        resp = client.get(
            '/analytics/reportes?metric=PURCHASES&period_type=MONTHLY&moneda=USD')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('chartEvolucion', html)
        self.assertIn('chartDetalle', html)
        self.assertIn('chartGasto', html)
        self.assertIn('cdn.jsdelivr.net/npm/chart.js', html)
        self.assertIn('window.RECORTES', html)

    def test_pagina_reportes_mermas_muestra_cada_registro_y_grafico(self):
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 10), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('3.00'),
                      total_cost=Decimal('15.00'), currency='USD')
        db.session.add(merma)
        db.session.flush()
        db.session.add(WasteDetail(
            waste_id=merma.id, product_id=self.harina.id,
            waste_type_id=self.vendido.id, lot_number='L-1',
            quantity=Decimal('3.00'), unit_cost=Decimal('5.00'),
            subtotal_cost=Decimal('15.00'), status='APROBADO'))
        db.session.commit()
        graficos = svc.construir_graficos(
            svc.construir_reporte(
                svc.ReportFilters(location_id=self.sede_a.id, metric='WASTE',
                                  period_type='MONTHLY', moneda='USD'),
                self.admin.id),
            svc.obtener_ranking([self.sede_a.id, self.sede_b.id], 'WASTE',
                                None, 'MONTHLY', 'USD'), 'USD')
        self.assertEqual(graficos['detalle']['titulo'],
                         'Mermas del período (cada registro real)')
        self.assertEqual(graficos['detalle']['labels'],
                         ['10/09/2026 Vencido'])
        self.assertEqual(graficos['detalle']['values'], [15.0])

    def test_mermas_resumen_y_cada_registro_no_convierten(self):
        merma = Waste(location_id=self.sede_a.id, waste_type_id=self.vendido.id,
                      date=datetime(2026, 9, 8, 10), user_id=self.admin.id,
                      status='APROBADO',
                      total_quantity=Decimal('30.00'),
                      total_cost=Decimal('2100.00'), currency='USD')
        db.session.add(merma)
        db.session.commit()

        mermas = obtener_mermas_detalle([self.sede_a.id],
                                        datetime(2026, 9, 1),
                                        datetime(2026, 9, 30))
        self.assertEqual(len(mermas), 1)
        self.assertEqual(mermas[0]['cost'], _redondo('2100.00'))
        self.assertEqual(mermas[0]['currency'], 'USD')

        resumen = obtener_mermas_resumen([self.sede_a.id],
                                         datetime(2026, 9, 1),
                                         datetime(2026, 9, 30))
        self.assertEqual(resumen['total']['USD'], _redondo('2100.00'))
        self.assertEqual(resumen['total']['EUR'], _redondo('0.00'))
        self.assertEqual(resumen['por_sede']['Sede La Candelaria']['USD'],
                         _redondo('2100.00'))

    def test_mermas_resumen_por_sede_no_filtra_montos_de_otras_sedes(self):
        db.session.add(Waste(location_id=self.sede_a.id,
                             waste_type_id=self.vendido.id,
                             date=datetime(2026, 9, 8), user_id=self.admin.id,
                             status='APROBADO',
                             total_quantity=Decimal('10.00'),
                             total_cost=Decimal('100.00'), currency='USD'))
        db.session.add(Waste(location_id=self.sede_b.id,
                             waste_type_id=self.vendido.id,
                             date=datetime(2026, 9, 9), user_id=self.admin.id,
                             status='APROBADO',
                             total_quantity=Decimal('20.00'),
                             total_cost=Decimal('200.00'), currency='EUR'))
        db.session.commit()

        resumen = obtener_mermas_resumen([self.sede_a.id, self.sede_b.id],
                                         datetime(2026, 9, 1),
                                         datetime(2026, 9, 30))
        self.assertEqual(resumen['total']['USD'], _redondo('100.00'))
        self.assertEqual(resumen['total']['EUR'], _redondo('200.00'))
        self.assertEqual(
            resumen['por_sede']['Sede La Candelaria']['USD'],
            _redondo('100.00'))
        self.assertEqual(resumen['por_sede']['Sede La Candelaria']['EUR'],
                         _redondo('0.00'))
        self.assertEqual(resumen['por_sede']['Sede Bello Monte']['EUR'],
                         _redondo('200.00'))
        self.assertEqual(resumen['por_sede']['Sede Bello Monte']['USD'],
                         _redondo('0.00'))

    def test_gasto_categorias_montos_exactos_por_periodo(self):
        macro = Category(name='Harinas Contables')
        db.session.add(macro)
        db.session.flush()
        pt = ProductType(name='Harina PT', category_id=macro.id)
        db.session.add(pt)
        db.session.flush()
        self.harina.product_type_id = pt.id
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('40000.00'), currency='USD',
            invoice_url='https://img/factura2.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-800',
            quantity=Decimal('500.00'), foreign_price=Decimal('80.00'),
            price_bs=Decimal('65175.26')))
        db.session.commit()

        gasto = svc.obtener_gasto_categorias('MONTHLY', date(2026, 9, 15),
                                             'USD', meses=3)
        self.assertEqual(gasto['labels'][-1], 'Septiembre 2026')
        harinas = next((s for s in gasto['series']
                        if s['name'] == 'Harinas Contables'), None)
        self.assertIsNotNone(harinas)
        self.assertEqual(harinas['values'][-1], _redondo('40000.00'))
        self.assertEqual(gasto['totales'][-1], _redondo('40000.00'))

    def test_gasto_categorias_sin_categoria_agrupa_como_sin_categoria(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('25.00'), currency='USD',
            invoice_url='https://img/factura3.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.jamon.id, lot_number='S/L',
            quantity=Decimal('5.00'), foreign_price=Decimal('5.00'),
            price_bs=Decimal('4073.45')))
        db.session.commit()

        gasto = svc.obtener_gasto_categorias('MONTHLY', date(2026, 9, 15),
                                             'USD', meses=1)
        nombres = [s['name'] for s in gasto['series']]
        self.assertIn('Sin categoría', nombres)
        self.assertEqual(gasto['totales'][-1], _redondo('25.00'))

    def test_evolucion_gasto_usa_datos_reales_de_compras(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('40000.00'), currency='USD',
            invoice_url='https://img/factura4.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-9',
            quantity=Decimal('500.00'), foreign_price=Decimal('80.00'),
            price_bs=Decimal('65175.26')))
        db.session.commit()

        evol = svc.obtener_evolucion_gasto('MONTHLY', date(2026, 9, 15),
                                           'USD', meses=3)
        self.assertEqual(evol[-1]['label'], 'Septiembre 2026')
        self.assertEqual(evol[-1]['value'], _redondo('40000.00'))
        self.assertEqual(evol[0]['value'], _redondo('0.00'))

    def test_construir_graficos_evolucion_de_dinero_es_real(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8),
            total_amount=Decimal('40000.00'), currency='USD',
            invoice_url='https://img/factura5.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-10',
            quantity=Decimal('500.00'), foreign_price=Decimal('80.00'),
            price_bs=Decimal('65175.26')))
        db.session.commit()
        reporte = svc.construir_reporte(
            svc.ReportFilters(location_id=None, metric='CONSOLIDATED',
                              period_type='MONTHLY', moneda='USD'),
            self.admin.id)
        graficos = svc.construir_graficos(
            reporte, svc.obtener_ranking([self.sede_a.id], 'PURCHASES',
                                         None, 'MONTHLY', 'USD'), 'USD')
        self.assertEqual(graficos['evolucion'][-1]['value'],
                         _redondo('40000.00'))

    def test_gasto_no_convierte_y_respeta_moneda_original(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 8, 12),
            total_amount=Decimal('40000.00'), currency='USD',
            invoice_url='https://img/factura6.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-11',
            quantity=Decimal('500.00'), foreign_price=Decimal('80.00'),
            price_bs=Decimal('65175.26')))
        db.session.commit()

        # En USD el gasto exacto aparece; en EUR queda 0 porque no hubo compras EUR.
        gasto_usd = svc.obtener_gasto_categorias('MONTHLY', date(2026, 9, 15),
                                                 'USD', meses=1)
        self.assertEqual(gasto_usd['totales'][-1], _redondo('40000.00'))
        gasto_eur = svc.obtener_gasto_categorias('MONTHLY', date(2026, 9, 15),
                                                 'EUR', meses=1)
        self.assertEqual(gasto_eur['totales'][-1], _redondo('0.00'))

    def test_consumo_valorizado_usa_ultimo_precio_de_compra(self):
        compra = Purchase(
            supplier_id=self.proveedor.id, purchase_date=datetime(2026, 9, 7),
            total_amount=Decimal('2100.00'), currency='USD',
            invoice_url='https://img/factura7.png', status='COMPLETADO',
            user_id=self.admin.id)
        db.session.add(compra)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=compra.id, product_id=self.harina.id, lot_number='L-C2',
            quantity=Decimal('30.00'), foreign_price=Decimal('70.00'),
            price_bs=Decimal('57028.36')))
        db.session.add(AuditLog(
            affected_table='inventory', action='GASTO_COCINA',
            location_id=self.sede_a.id, user_id=self.admin.id,
            timestamp=datetime(2026, 9, 8, 12),
            changed_data={'product_id': self.harina.id, 'lot_number': 'L-C2',
                          'quantity_changed': 30}))
        db.session.add(AuditLog(
            affected_table='inventory', action='CONSUMO_COCINA',
            location_id=self.sede_a.id, user_id=self.admin.id,
            timestamp=datetime(2026, 9, 9, 12),
            changed_data={'product_id': self.harina.id, 'lot_number': 'N/A',
                          'quantity_changed': 1}))
        db.session.commit()

        consumo = obtener_consumo_valorizado(
            [self.sede_a.id], datetime(2026, 9, 1), datetime(2026, 9, 30))
        # 30×70 + 1×70 = 2170 USD, sin conversión (EUR/BS en 0)
        self.assertEqual(consumo['total']['USD'], _redondo('2170.00'))
        self.assertEqual(consumo['total']['EUR'], _redondo('0.00'))
        self.assertEqual(consumo['por_sede']['Sede La Candelaria']['USD'],
                         _redondo('2170.00'))

    # ------------------------------------------------- sidebar ------------
    def test_sidebar_muestra_estadisticas_para_admin_y_finanzas(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.admin.id)
        html = client.get('/analytics/reportes').get_data(as_text=True)
        self.assertIn('ESTADÍSTICAS', html)
        self.assertIn('/analytics/reportes', html)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(self.financiero.id)
        html = client.get('/analytics/reportes').get_data(as_text=True)
        self.assertIn('ESTADÍSTICAS', html)


if __name__ == '__main__':
    unittest.main()