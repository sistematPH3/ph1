"""Pruebas de regresión de Gestión de Compras.

Cada caso cubre un bug corregido: precio de anexos, stock agregado, límites de
tiempo, validación de estado, preservation de vencimiento/lote, tasa de cambio y
normalización de moneda.
"""
import os
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

CERO_TEST = Decimal('0.00')

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

from app import create_app, db  # noqa: E402
from app.models import (AppParameter, Category, Inventory,  # noqa: E402
                        Location, Product, ProductType, Purchase,
                        PurchaseAuditLog, PurchaseDetail, Role, Supplier, User)
from app.logistics.repositories.purchase_management_repository import (  # noqa: E402
    PurchaseManagementRepository)
from app.logistics.requests.purchase_validators import (  # noqa: E402
    PurchaseValidator, es_moneda_bs, normalizar_moneda, normalizar_numero)
from app.logistics.services.purchase_management_service import (  # noqa: E402
    PurchaseManagementService)
from app.time_utils import current_ve_time  # noqa: E402


class FakeUser:
    def __init__(self, user_id=1, role_id=1):
        self.id = user_id
        self.role_id = role_id


class PurchaseManagementTestBase(unittest.TestCase):

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

        self.rol = Role(name="Administrator")
        self.central = Location(id=1, name="Almacén Central", state="Caracas",
                                is_active=True)
        db.session.add_all([self.rol, self.central])
        db.session.flush()

        self.admin = User(name="Admin", email="admin@ph.test",
                          password_hash="x", role_id=self.rol.id)
        self.otro = User(name="Comprador", email="otro@ph.test",
                         password_hash="x", role_id=self.rol.id)
        self.proveedor = Supplier(name="Proveedor Uno", tax_id="J-1")
        db.session.add_all([self.admin, self.otro, self.proveedor])
        db.session.flush()

        self.categoria = Category(name="Almaceneria")
        db.session.add(self.categoria)
        db.session.flush()

        self.tipo = ProductType(name="Almacen", category_id=self.categoria.id,
                                shelf_life_days=30)
        db.session.add(self.tipo)
        db.session.flush()

        self.prod_a = Product(name="Producto A", sku="PA-01",
                               unit_of_measure="KG", product_type_id=self.tipo.id,
                               min_stock=Decimal('5.00'))
        self.prod_b = Product(name="Producto B", sku="PB-01",
                               unit_of_measure="KG", product_type_id=self.tipo.id,
                               min_stock=Decimal('5.00'))
        db.session.add_all([self.prod_a, self.prod_b])
        db.session.commit()

        self.repo = PurchaseManagementRepository(db)
        self.service = PurchaseManagementService(self.repo)
        # El servicio identifica al administrador por role_id == 1.
        self.user = FakeUser(self.admin.id, 1)
        self.otro_user = FakeUser(self.otro.id, 7)

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # -- helpers -------------------------------------------------------
    def crear_compra(self, status='COMPLETED', moneda='USD', tasa=Decimal('10.0000'),
                     dias_atras=0, horas_atras=0, renglones=None, sin_proveedor=False):
        compra = Purchase(
            supplier_id=None if sin_proveedor else self.proveedor.id,
            purchase_date=current_ve_time() - timedelta(days=dias_atras, hours=horas_atras),
            total_amount=Decimal('0.00'),
            currency=moneda,
            exchange_rate=tasa,
            invoice_url="f.pdf",
            user_id=self.admin.id,
            status=status
        )
        db.session.add(compra)
        db.session.flush()
        if renglones:
            # Los detalles guardados usan foreign_price como precio UNITARIO
            # (así lo almacena el registro de compras): el total es cantidad x precio.
            total = CERO_TEST
            for product_id, cantidad, precio in renglones:
                total += cantidad * precio
                db.session.add(PurchaseDetail(
                    purchase_id=compra.id,
                    product_id=product_id,
                    quantity=cantidad,
                    foreign_price=precio,
                    price_bs=precio * tasa,
                    lot_number=f"LOT-{product_id}-{compra.id}",
                    expiration_date=date(2027, 1, 31)
                ))
                # El registro real de compra también crea/actualiza el inventario.
                inv = db.session.query(Inventory).filter_by(
                    location_id=1, product_id=product_id).first()
                if inv is None:
                    db.session.add(Inventory(
                        location_id=1, product_id=product_id,
                        current_quantity=cantidad,
                        min_stock=Decimal('5.00'),
                        transit_quantity=Decimal('0.00'),
                        reserved_quantity=Decimal('0.00')))
                else:
                    inv.current_quantity = (Decimal(str(inv.current_quantity))
                                            + cantidad)
            compra.total_amount = total
            db.session.commit()
        return compra

    def stock(self, product_id):
        inv = db.session.query(Inventory).filter_by(
            location_id=1, product_id=product_id).first()
        return inv

    def total_stock(self, product_id):
        inv = self.stock(product_id)
        return inv.current_quantity if inv else None

    def item(self, detail_id, **kwargs):
        # El payload de edición usa foreign_price como TOTAL de línea.
        base = {'id': str(detail_id), 'quantity': 10, 'foreign_price': 5}
        base.update(kwargs)
        return base


class PrecioAnexosTest(PurchaseManagementTestBase):
    """El modal de edición envía el TOTAL de la línea: el unitario del detalle
    se deriva dividiéndolo entre la cantidad (igual que el registro)."""

    def test_anexo_guarda_el_total_de_linea_y_deriva_el_unitario(self):
        compra = self.crear_compra(moneda='USD', tasa=Decimal('10.0000'),
                                   renglones=[(self.prod_a.id, Decimal('2.00'),
                                               Decimal('5.00'))])
        db.session.commit()

        # 10 unidades por 50.00 de total => unitario 5.00.
        items = [
            self.item(self._detalle_id(compra), quantity=2, foreign_price=10),
            {'id': 'new_1', 'product_id': self.prod_b.id, 'quantity': 10,
             'foreign_price': 50, 'expiration_date': '', 'lot_number': ''},
        ]
        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, items,
                                               "anexo de prueba"))

        nuevo = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_b.id).one()
        # 50.00 de total entre 10 unidades => unitario 5.00.
        self.assertEqual(nuevo.quantity, Decimal('10.00'))
        self.assertEqual(nuevo.foreign_price, Decimal('5.00'))
        self.assertEqual(nuevo.price_bs, Decimal('50.00'))
        self.assertEqual(compra.total_amount, Decimal('60.00'))
        self.assertEqual(self.total_stock(self.prod_b.id), Decimal('10.00'))

    def test_anexo_no_altera_el_renglon_existente(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle_id = self._detalle_id(compra)
        db.session.commit()

        items = [
            self.item(detalle_id, quantity=2, foreign_price=10),
            {'id': 'new_1', 'product_id': self.prod_b.id, 'quantity': 10,
             'foreign_price': 50, 'expiration_date': '', 'lot_number': ''},
        ]
        self.repo.logical_edit(compra.id, self.admin.id, items, "anexo")

        original = db.session.get(PurchaseDetail, detalle_id)
        self.assertEqual(original.foreign_price, Decimal('5.00'))
        self.assertEqual(original.quantity, Decimal('2.00'))

    def test_edicion_sin_anexos_conserva_el_total(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('4.00'),
                                              Decimal('3.00'))])
        detalle_id = self._detalle_id(compra)
        db.session.commit()

        # Total de línea 12.00 para 4 unidades => unitario 3.00.
        items = [self.item(detalle_id, quantity=4, foreign_price=12)]
        self.repo.logical_edit(compra.id, self.admin.id, items, "sin cambios")

        self.assertEqual(compra.total_amount, Decimal('12.00'))

    @staticmethod
    def _detalle_id(compra):
        return db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id


class StockDisponibleTest(PurchaseManagementTestBase):
    """Bugs: se comparaba contra current_quantity ignorando reserva/transito,
    y el chequeo no agregaba duplicados por producto."""

    def test_no_se_puede_reducir_stock_comprometido_en_transito(self):
        # Físico 10, en tránsito 8 => solo 2 disponibles. Bajar el renglón a 5
        # exigiría quitar 5 unidades de las 2 realmente disponibles.
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('10.00'),
                                              Decimal('5.00'))])
        inv = self.stock(self.prod_a.id)
        inv.transit_quantity = Decimal('8.00')
        db.session.commit()

        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        items = [self.item(detalle_id, quantity=5, foreign_price=5)]

        with self.assertRaises(ValueError) as ctx:
            self.repo.logical_edit(compra.id, self.admin.id, items, "reducir")
        self.assertIn("Producto A", str(ctx.exception))
        # El stock físico no se tocó al rechazar.
        self.assertEqual(self.total_stock(self.prod_a.id), Decimal('10.00'))

    def test_reduccion_dentro_del_disponible_si_se_permite(self):
        # Mismo escenario pero bajando solo 1: hay 2 disponibles, así que vale.
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('10.00'),
                                              Decimal('5.00'))])
        self.stock(self.prod_a.id).transit_quantity = Decimal('8.00')
        db.session.commit()

        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        items = [self.item(detalle_id, quantity=9, foreign_price=5)]
        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, items,
                                               "reducir dentro del disponible"))
        self.assertEqual(self.total_stock(self.prod_a.id), Decimal('9.00'))

    def test_no_se_puede_anular_stock_con_merma_pendiente(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('10.00'),
                                              Decimal('5.00'))])
        inv = self.stock(self.prod_a.id)
        inv.reserved_quantity = Decimal('7.00')
        db.session.commit()

        with self.assertRaises(ValueError):
            self.repo.logical_annulment(compra.id, self.admin.id)
        self.assertEqual(compra.status, 'COMPLETED')
        self.assertEqual(self.total_stock(self.prod_a.id), Decimal('10.00'))

    def test_duplicados_del_mismo_producto_no_dejan_stock_negativo(self):
        # Dos renglones del mismo producto: 10 + 10, pero solo 15 disponibles.
        # El chequeo por renglón pasaba ambos y dejaba el stock en -5.
        compra = self.crear_compra(
            renglones=[(self.prod_a.id, Decimal('10.00'), Decimal('5.00')),
                       (self.prod_a.id, Decimal('10.00'), Decimal('6.00'))])
        self.stock(self.prod_a.id).current_quantity = Decimal('15.00')
        db.session.commit()

        with self.assertRaises(ValueError):
            self.repo.logical_annulment(compra.id, self.admin.id)
        self.assertEqual(self.total_stock(self.prod_a.id), Decimal('15.00'))
        self.assertEqual(compra.status, 'COMPLETED')

    def test_reduccion_neta_valida_agregando_renglones_del_mismo_producto(self):
        # Subir un renglón y bajar otro del mismo producto es válido: el delta
        # neto no reduce el stock, aunque cada renglón por separado lo haría.
        compra = self.crear_compra(
            renglones=[(self.prod_a.id, Decimal('10.00'), Decimal('5.00')),
                       (self.prod_a.id, Decimal('10.00'), Decimal('6.00'))])
        db.session.commit()

        ids = [d.id for d in db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).order_by(PurchaseDetail.id).all()]
        # Totales de línea: 15 x 5.00 = 75.00 y 5 x 6.00 = 30.00.
        items = [self.item(ids[0], quantity=15, foreign_price=75),
                 self.item(ids[1], quantity=5, foreign_price=30)]

        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, items,
                                               "rebalanceo"))
        self.assertEqual(self.total_stock(self.prod_a.id), Decimal('20.00'))
        self.assertEqual(compra.total_amount, Decimal('105.00'))


class LimitesTiempoTest(PurchaseManagementTestBase):
    """Bug: .days truncaba y convertia el limite de 7 dias en 8."""

    def test_admin_puede_operar_hasta_7_dias_exactos(self):
        compra = self.crear_compra(dias_atras=6, horas_atras=23)
        self.assertTrue(self.service.can_modify(compra, self.user))

    def test_admin_no_puede_operar_pasados_7_dias(self):
        compra = self.crear_compra(dias_atras=7, horas_atras=1)
        self.assertFalse(self.service.can_modify(compra, self.user))
        with self.assertRaises(ValueError) as ctx:
            self.service.process_annulment(compra.id, self.user)
        self.assertIn("7 días", str(ctx.exception))

    def test_limite_por_horas_para_no_admin(self):
        usuario = self.otro_user
        reciente = self.crear_compra(dias_atras=0, horas_atras=23)
        self.assertTrue(self.service.can_modify(reciente, usuario))

        viejo = self.crear_compra(dias_atras=0, horas_atras=25)
        self.assertFalse(self.service.can_modify(viejo, usuario))
        with self.assertRaises(ValueError) as ctx:
            self.service.process_edit(viejo.id, usuario, [], "motivo")
        self.assertIn("24 horas", str(ctx.exception))

    def test_listado_y_proceso_coinciden_en_can_modify(self):
        for horas in (1, 23, 25, 24 * 7 + 1):
            with self.subTest(horas=horas):
                compra = self.crear_compra(dias_atras=0, horas_atras=horas)
                db.session.commit()
                historiales = self.service.get_formatted_history(
                    current_user=self.user, status='COMPLETED')
                fila = next(h for h in historiales if h['id'] == compra.id)
                self.assertEqual(fila['can_modify'],
                                 self.service.can_modify(compra, self.user))

    def test_parametro_no_numerico_no_rompe_el_listado(self):
        db.session.add(AppParameter(key='PURCHASE_ADMIN_EDIT_DAYS',
                                     value='no-es-un-numero'))
        db.session.commit()
        limites = self.service._get_time_limits()
        self.assertEqual(limites['admin_days'], 7)
        self.assertEqual(limites['other_hours'], 24)


class EstadoCompraTest(PurchaseManagementTestBase):
    """Bug: el backend solo rechazaba ANNULLED, la UI solo COMPLETED."""

    def test_compra_pendiente_no_se_puede_editar_ni_anular(self):
        for status in ('PENDING', 'CANCELLED', 'ANNULLED'):
            with self.subTest(status=status):
                compra = self.crear_compra(status=status,
                                           renglones=[(self.prod_a.id,
                                                       Decimal('5.00'),
                                                       Decimal('5.00'))])
                db.session.commit()
                self.assertFalse(self.service.can_modify(compra, self.user))
                with self.assertRaises(ValueError):
                    self.service.process_annulment(compra.id, self.user)
                self.assertEqual(compra.status, status)

    def test_compras_sin_proveedor_no_desaparecen_del_listado(self):
        self.crear_compra(sin_proveedor=True, renglones=[
            (self.prod_a.id, Decimal('1.00'), Decimal('1.00'))])
        db.session.commit()
        historiales = self.service.get_formatted_history(current_user=self.user)
        self.assertEqual(len(historiales), 1)
        self.assertEqual(historiales[0]['supplier_name'], "Proveedor N/A")


class VencimientoYLoteTest(PurchaseManagementTestBase):
    """Bug: al editar un renglón se perdían la fecha y el lote ya guardados.

    Contrato: si el cliente omite la clave, se conserva lo guardado; si la
    envía vacía, es una limpieza explícita del usuario."""

    def test_omitir_las_claves_conserva_las_fechas(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one()
        detalle_id = detalle.id
        db.session.commit()

        # Solo cambia la cantidad: el payload no menciona fecha ni lote.
        items = [{'id': str(detalle_id), 'quantity': 3, 'foreign_price': 5}]
        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, items,
                                               "solo cantidad"))

        detalle = db.session.get(PurchaseDetail, detalle_id)
        self.assertEqual(detalle.expiration_date, date(2027, 1, 31))
        self.assertTrue(detalle.lot_number)
        self.assertEqual(detalle.lot_number, f"LOT-{self.prod_a.id}-{compra.id}")

    def test_enviar_expiracion_vacia_la_limpia(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one()
        detalle_id = detalle.id
        db.session.commit()

        items = [{'id': str(detalle_id), 'quantity': 2, 'foreign_price': 5,
                  'expiration_date': '', 'lot_number': ''}]
        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, items,
                                               "limpieza explícita"))

        detalle = db.session.get(PurchaseDetail, detalle_id)
        self.assertIsNone(detalle.expiration_date)
        self.assertIsNone(detalle.lot_number)

    def test_expiracion_explicita_si_reemplaza_la_guardada(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()

        items = [{'id': str(detalle_id), 'quantity': 2, 'foreign_price': 5,
                  'expiration_date': '2028-06-30', 'lot_number': 'LOT-NUEVO'}]
        self.repo.logical_edit(compra.id, self.admin.id, items, "nueva fecha")

        detalle = db.session.get(PurchaseDetail, detalle_id)
        self.assertEqual(detalle.expiration_date, date(2028, 6, 30))
        self.assertEqual(detalle.lot_number, 'LOT-NUEVO')

    def test_anexo_calcula_vencimiento_desde_la_vida_util(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('1.00'),
                                              Decimal('5.00'))])
        db.session.commit()

        items = [
            self.item(self._detalle_id(compra), quantity=1, foreign_price=5),
            {'id': 'new_1', 'product_id': self.prod_b.id, 'quantity': 2,
             'foreign_price': 5, 'expiration_date': '', 'lot_number': ''},
        ]
        self.repo.logical_edit(compra.id, self.admin.id, items, "anexo")

        nuevo = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_b.id).one()
        self.assertIsNotNone(nuevo.expiration_date)
        self.assertTrue(nuevo.lot_number)

    def test_dos_anexos_del_mismo_producto_no_comparten_lote(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('1.00'),
                                              Decimal('5.00'))])
        db.session.commit()

        items = [
            self.item(self._detalle_id(compra), quantity=1, foreign_price=5),
            {'id': 'new_1', 'product_id': self.prod_b.id, 'quantity': 1,
             'foreign_price': 5, 'expiration_date': '', 'lot_number': ''},
            {'id': 'new_2', 'product_id': self.prod_b.id, 'quantity': 1,
             'foreign_price': 5, 'expiration_date': '', 'lot_number': ''},
        ]
        self.repo.logical_edit(compra.id, self.admin.id, items, "dos anexos")

        lotes = [d.lot_number for d in db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_b.id).all()]
        self.assertEqual(len(lotes), 2)
        self.assertEqual(len(set(lotes)), 2, f"lotes repetidos: {lotes}")

    @staticmethod
    def _detalle_id(compra):
        return db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id


class TasaCambioTest(PurchaseManagementTestBase):
    """Bug: la edicion revaluaba con la tasa del dia, no la de la factura."""

    def test_edicion_conserva_la_tasa_de_la_factura(self):
        compra = self.crear_compra(moneda='USD', tasa=Decimal('10.0000'),
                                   renglones=[(self.prod_a.id, Decimal('2.00'),
                                               Decimal('5.00'))])
        db.session.commit()

        items = [self.item(self._detalle_id(compra), quantity=2, foreign_price=14)]
        self.repo.logical_edit(compra.id, self.admin.id, items, "nuevo precio")

        self.assertEqual(compra.exchange_rate, Decimal('10.0000'))
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one()
        # 7.00 x 10.00 (tasa original), no x la tasa vigente.
        self.assertEqual(detalle.price_bs, Decimal('70.00'))

    def test_compra_en_bs_no_multiplica_por_tasa(self):
        compra = self.crear_compra(moneda='BS', tasa=Decimal('500.0000'),
                                   renglones=[(self.prod_a.id, Decimal('2.00'),
                                               Decimal('25.00'))])
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()

        items = [self.item(detalle_id, quantity=2, foreign_price=50)]
        self.repo.logical_edit(compra.id, self.admin.id, items, "precio bs")

        detalle = db.session.get(PurchaseDetail, detalle_id)
        self.assertEqual(detalle.price_bs, Decimal('25.00'))
        historiales = self.service.get_formatted_history(
            current_user=self.user, status='COMPLETED')
        self.assertEqual(historiales[0]['total_bs'], Decimal('50.00'))

    def test_sin_tasa_guardada_usa_la_vigente_y_la_registra(self):
        compra = self.crear_compra(moneda='USD', tasa=Decimal('10.0000'),
                                   renglones=[(self.prod_a.id, Decimal('2.00'),
                                               Decimal('5.00'))])
        compra.exchange_rate = None
        db.session.add(ExchangeRateHistoryFactory(self, 'USD', Decimal('20.0000')))
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()

        items = [self.item(detalle_id, quantity=2, foreign_price=10)]
        self.repo.logical_edit(compra.id, self.admin.id, items, "sin tasa")

        self.assertEqual(compra.exchange_rate, Decimal('20.0000'))
        detalle = db.session.get(PurchaseDetail, detalle_id)
        self.assertEqual(detalle.price_bs, Decimal('100.00'))

    def test_sin_tasa_guardada_ni_vigente_falla_con_mensaje_claro(self):
        compra = self.crear_compra(moneda='EUR',
                                   renglones=[(self.prod_a.id, Decimal('2.00'),
                                               Decimal('5.00'))])
        compra.exchange_rate = None
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()

        items = [self.item(detalle_id, quantity=2, foreign_price=5)]
        with self.assertRaises(ValueError) as ctx:
            self.repo.logical_edit(compra.id, self.admin.id, items, "sin tasa")
        self.assertIn("tasa de cambio", str(ctx.exception))

    def test_sin_tasa_no_inventa_un_total_de_cero(self):
        # En USD no hay conversión posible: se devuelve None, no 0,00, que en
        # pantalla parecía una compra de cero bolívares. En Bs no aplica.
        for moneda, esperado in (('USD', None), ('BS', Decimal('10.00'))):
            with self.subTest(moneda=moneda):
                compra = self.crear_compra(moneda=moneda, renglones=[
                    (self.prod_a.id, Decimal('1.00'), Decimal('10.00'))])
                compra.exchange_rate = None
                db.session.commit()

                historiales = self.service.get_formatted_history(
                    current_user=self.user)
                fila = next(h for h in historiales if h['id'] == compra.id)
                self.assertEqual(fila['total_bs'], esperado)
                self.assertIsNone(fila['exchange_rate'])

    def test_historial_refleja_los_precios_tras_editar(self):
        compra = self.crear_compra(moneda='USD', renglones=[
            (self.prod_a.id, Decimal('2.00'), Decimal('5.00'))])
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()

        items = [self.item(detalle_id, quantity=2, foreign_price=14)]
        self.repo.logical_edit(compra.id, self.admin.id, items, "precio nuevo")

        historiales = self.service.get_formatted_history(current_user=self.user)
        fila = next(h for h in historiales if h['id'] == compra.id)
        self.assertEqual(fila['total_bs'], Decimal('140.00'))

    @staticmethod
    def _detalle_id(compra):
        return db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id


def ExchangeRateHistoryFactory(case, currency, rate):
    from app.models import ExchangeRateHistory
    return ExchangeRateHistory(currency=currency, rate=rate, source='BCV',
                               timestamp=datetime.utcnow(), user_id=case.admin.id)


class NormalizacionMonedaTest(unittest.TestCase):

    def test_aliases_de_bolivares(self):
        for alias in ('BS', 'bs', 'VES', 'BSS', 'BS.', ' Bs '):
            with self.subTest(alias=alias):
                self.assertTrue(es_moneda_bs(alias))
                self.assertEqual(normalizar_moneda(alias), 'BS')

    def test_monedas_extranjeras_no_son_bolivares(self):
        for moneda in ('USD', 'EUR', 'usd', 'MXN'):
            with self.subTest(moneda=moneda):
                self.assertFalse(es_moneda_bs(moneda))

    def test_validador_rechaza_monedas_no_permitidas(self):
        errors = PurchaseValidator.validate_header({
            'supplier_id': 1, 'currency': 'MXN',
            'exchange_rate': '10', 'user_id': 1})
        self.assertIn('currency', errors)


class ValidacionEntradaTest(unittest.TestCase):
    """Bugs: Decimal(str()) sin normalizar, fecha sin validar, reason sin tipo."""

    def test_cantidad_y_precio_en_formato_es_ve_pasan_la_validacion(self):
        items = [{'id': '1', 'quantity': '1.000,00',
                  'foreign_price': '2.000,50'}]
        self.assertFalse(PurchaseValidator.validate_edit_items(items))

    def test_expiracion_invalida_se_reporta_como_error_de_validacion(self):
        items = [{'id': '1', 'quantity': 1, 'foreign_price': 1,
                  'expiration_date': '31/12/2027'}]
        errors = PurchaseValidator.validate_edit_items(items)
        self.assertTrue(any('expiration_date' in k for k in errors))

    def test_expiracion_valida_no_genera_error(self):
        items = [{'id': '1', 'quantity': 1, 'foreign_price': 1,
                  'expiration_date': '2027-12-31'}]
        self.assertFalse(PurchaseValidator.validate_edit_items(items))

    def test_lote_muy_largo_se_reporta(self):
        items = [{'id': '1', 'quantity': 1, 'foreign_price': 1,
                  'lot_number': 'L' * 60}]
        errors = PurchaseValidator.validate_edit_items(items)
        self.assertTrue(any('lot_number' in k for k in errors))

    def test_id_de_insumo_no_numerico_se_reporta(self):
        items = [{'id': 'abc', 'quantity': 1, 'foreign_price': 1}]
        errors = PurchaseValidator.validate_edit_items(items)
        self.assertTrue(any(k.endswith('_id') for k in errors))

    def test_motivo_invalido(self):
        self.assertIsNone(PurchaseValidator.validate_edit_reason("ajuste correcto"))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason(""))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason("   "))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason("abc"))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason(12345))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason(None))
        self.assertIsNotNone(PurchaseValidator.validate_edit_reason("x" * 600))

    def test_item_no_dict_se_reporta_en_vez_de_romperse(self):
        # Antes: item.get() sobre un string lanzaba AttributeError -> 500.
        for basura in ("texto", None, 42, ["a"]):
            errors = PurchaseValidator.validate_edit_items([basura])
            self.assertIn('item_0', errors, f"sin error para {basura!r}")
            self.assertIsInstance(errors['item_0'], str)

    def test_cero_con_punto_es_decimal_y_no_miles(self):
        # "0.500" se leía como 500 (1000x). Nadie escribe 0.500 para 500.
        self.assertEqual(Decimal(normalizar_numero("0.500")), Decimal("0.500"))
        self.assertEqual(Decimal(normalizar_numero("0.050")), Decimal("0.050"))
        self.assertEqual(Decimal(normalizar_numero("0.001")), Decimal("0.001"))
        # Los miles de verdad se siguen respetando.
        self.assertEqual(Decimal(normalizar_numero("1.500")), Decimal("1500"))
        self.assertEqual(Decimal(normalizar_numero("2.000.000")), Decimal("2000000"))
        self.assertEqual(Decimal(normalizar_numero("12.500")), Decimal("12500"))
        # Y la coma decimal tampoco se rompió.
        self.assertEqual(Decimal(normalizar_numero("0,500")), Decimal("0.500"))
        self.assertEqual(Decimal(normalizar_numero("1.234,56")), Decimal("1234.56"))


class EliminacionRenglonTest(PurchaseManagementTestBase):
    """Un renglón que el cliente omite se elimina de la compra y su cantidad
    se revierte del inventario. Esa reversión debe validar disponibilidad."""

    def test_borrar_renglon_sin_stock_disponible_se_rechaza(self):
        compra = self.crear_compra(renglones=[
            (self.prod_a.id, Decimal('10.00'), Decimal('5.00')),
            (self.prod_b.id, Decimal('5.00'), Decimal('5.00')),
        ])
        # prod_a se consumió en otra operación: solo quedan 5 de las 10 que
        # aportó esta compra.
        self.stock(self.prod_a.id).current_quantity = Decimal('5.00')
        db.session.commit()

        det_b = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_b.id).one()
        items = [self.item(det_b.id, quantity=5)]

        with self.assertRaises(ValueError) as ctx:
            self.repo.logical_edit(compra.id, self.admin.id, items, "quite un renglón")
        self.assertIn("no se puede reducir", str(ctx.exception).lower())
        # Nada se aplicó: el renglón sigue y el stock no se movió.
        self.assertIsNotNone(db.session.get(PurchaseDetail, det_b.id))
        self.assertEqual(Decimal(str(self.total_stock(self.prod_a.id))),
                         Decimal('5.00'))

    def test_borrar_renglon_con_stock_suficiente_lo_revierte(self):
        compra = self.crear_compra(renglones=[
            (self.prod_a.id, Decimal('10.00'), Decimal('5.00')),
            (self.prod_b.id, Decimal('5.00'), Decimal('5.00')),
        ])
        self.assertEqual(Decimal(str(self.total_stock(self.prod_a.id))),
                         Decimal('10.00'))
        det_b = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_b.id).one()

        self.assertTrue(self.repo.logical_edit(
            compra.id, self.admin.id,
            [self.item(det_b.id, quantity=5, foreign_price=25)],
            "borré el insumo A"))

        self.assertEqual(Decimal(str(self.total_stock(self.prod_a.id))),
                         Decimal('0.00'))
        self.assertIsNone(db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=self.prod_a.id).first())
        self.assertEqual(Decimal(str(db.session.get(
            Purchase, compra.id).total_amount)), Decimal('25.00'))

    def test_borrar_entre_varios_renglones_del_mismo_producto_es_neto(self):
        # prod_a aparece dos veces: la suma de ambas reversiones decide.
        compra = self.crear_compra(renglones=[
            (self.prod_a.id, Decimal('4.00'), Decimal('5.00')),
            (self.prod_a.id, Decimal('3.00'), Decimal('5.00')),
        ])
        self.stock(self.prod_a.id).current_quantity = Decimal('6.00')
        db.session.commit()

        with self.assertRaises(ValueError):
            self.repo.logical_edit(compra.id, self.admin.id, [], "borro todo")
        # Y con stock suficiente se revierte el total de ambos (7), no uno solo.
        self.stock(self.prod_a.id).current_quantity = Decimal('7.00')
        db.session.commit()
        self.assertTrue(self.repo.logical_edit(
            compra.id, self.admin.id, [self.item('new_1', quantity=1,
                                                 foreign_price=2,
                                                 product_id=self.prod_b.id)],
            "reemplacé los renglones"))
        self.assertEqual(Decimal(str(self.total_stock(self.prod_a.id))),
                         Decimal('0.00'))


class LoteLargoTest(PurchaseManagementTestBase):
    """lot_number es VARCHAR(50): un SKU largo no puede desbordarlo."""

    def test_lote_generado_cabe_en_la_columna(self):
        largo = Product(name="SKU largo", sku="A" * 50, unit_of_measure="UND",
                        product_type_id=self.tipo.id, is_active=True)
        db.session.add(largo)
        db.session.commit()
        compra = self.crear_compra()

        lote = self.repo._generar_lote(largo, compra)
        self.assertLessEqual(len(lote), 50, f"lote de {len(lote)} caracteres")
        # Y debe poder guardarse de verdad, no solo medir bien.
        self.assertTrue(self.repo.logical_edit(compra.id, self.admin.id, [{
            'id': 'new_1', 'product_id': largo.id, 'quantity': 2,
            'foreign_price': 5, 'expiration_date': '',
            'lot_number': ''}], "anexo con SKU largo"))
        guardado = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id, product_id=largo.id).one()
        self.assertIsNotNone(guardado.lot_number)
        self.assertLessEqual(len(guardado.lot_number), 50)

    def test_lotes_correlativos_siguen_sin_repetirse(self):
        # El correlativo avanza con un contador compartido durante la edición
        # (como hace logical_edit) y con los lotes ya guardados en BD.
        compra = self.crear_compra()
        contador = {}
        vistos = {self.repo._generar_lote(self.prod_a, compra, contador)
                  for _ in range(3)}
        self.assertEqual(len(vistos), 3, f"lotes repetidos: {vistos}")
        for lote in vistos:
            self.assertLessEqual(len(lote), 50)

        # Y un cuarto anexo tras persistir los anteriores tampoco repite.
        for lote in vistos:
            db.session.add(PurchaseDetail(
                purchase_id=compra.id, product_id=self.prod_a.id,
                quantity=Decimal('1'), foreign_price=Decimal('5'),
                lot_number=lote))
        db.session.commit()
        siguiente = self.repo._generar_lote(self.prod_a, compra, {})
        self.assertNotIn(siguiente, vistos)
        self.assertLessEqual(len(siguiente), 50)


class UnaSolaEdicionTest(PurchaseManagementTestBase):
    """Regla: una compra solo se puede editar UNA vez.

    La segunda edición se rechaza en el servicio y también en el repositorio
    (para que una llamada directa no se salte la regla). El listado deja de
    ofrecer el botón de editar pero mantiene el de anular.
    """

    @staticmethod
    def _detalle_id(compra):
        return db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id

    def _crear_y_editar_una_vez(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle_id = self._detalle_id(compra)
        db.session.commit()
        items = [self.item(detalle_id, quantity=2, foreign_price=10)]
        self.assertTrue(self.service.process_edit(compra.id, self.user, items,
                                                  "primera edicion"))
        return compra, items

    def test_segunda_edicion_por_el_servicio_se_rechaza(self):
        compra, items = self._crear_y_editar_una_vez()

        with self.assertRaises(ValueError) as ctx:
            self.service.process_edit(compra.id, self.user, items,
                                      "segunda edicion")
        self.assertIn("una edición", str(ctx.exception).lower())

    def test_repositorio_tambien_bloquea_la_segunda_edicion(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        detalle_id = self._detalle_id(compra)
        db.session.commit()
        items = [self.item(detalle_id, quantity=2, foreign_price=10)]

        self.repo.logical_edit(compra.id, self.admin.id, items, "primera")
        with self.assertRaises(ValueError):
            self.repo.logical_edit(compra.id, self.admin.id, items, "segunda")

    def test_listado_marca_editada_y_conserva_la_anulacion(self):
        compra, _ = self._crear_y_editar_una_vez()

        fila = next(h for h in self.service.get_formatted_history(
            current_user=self.user) if h['id'] == compra.id)
        self.assertTrue(fila['already_edited'])
        self.assertFalse(fila['can_edit'])
        # Anular sigue disponible: la regla solo afecta a la edición.
        self.assertTrue(fila['can_modify'])

    def test_compra_sin_editar_si_se_puede_editar(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('2.00'),
                                              Decimal('5.00'))])
        db.session.commit()

        fila = next(h for h in self.service.get_formatted_history(
            current_user=self.user) if h['id'] == compra.id)
        self.assertFalse(fila['already_edited'])
        self.assertTrue(fila['can_edit'])


class FechaCompraTest(PurchaseManagementTestBase):
    """Regresión del desfase de 4 h: purchase_date se guarda en hora VE y así
    debe mostrarse/compararse.

    Antes el listado la convertía con utc_a_ve (le restaba 4 h) y can_modify
    comparaba contra UTC, cerrando la ventana de edición 4 h antes.
    """

    def test_listado_no_desplaza_la_fecha_de_compra(self):
        compra = self.crear_compra(dias_atras=0, horas_atras=2)
        db.session.commit()

        fila = next(h for h in self.service.get_formatted_history(
            current_user=self.user) if h['id'] == compra.id)

        # Se muestra la fecha tal cual se guardó (hora VE), sin restar 4 h.
        self.assertEqual(fila['purchase_date'], compra.purchase_date)

    def test_ventana_de_edicion_usa_el_reloj_ve(self):
        from unittest.mock import patch

        fixed = datetime(2026, 9, 30, 23, 30, 0)
        compra = self.crear_compra()
        compra.purchase_date = fixed - timedelta(hours=23)
        db.session.commit()

        with patch('app.logistics.services.purchase_management_service'
                   '.current_ve_time', return_value=fixed):
            # 23 h después (reloj VE) sigue dentro de las 24 h del comprador.
            self.assertTrue(self.service.can_modify(compra, self.otro_user))

            compra.purchase_date = fixed - timedelta(hours=25)
            db.session.commit()
            # 25 h después ya expiró: el límite es de 24 h reales, no 20.
            self.assertFalse(self.service.can_modify(compra, self.otro_user))


class BloqueoStockTest(PurchaseManagementTestBase):
    """Regresión del hallazgo #5: las escrituras de stock de compras toman el
    bloqueo de fila (SELECT ... FOR UPDATE).

    Sin el lock, dos operaciones concurrentes sobre el Almacén Central leían el
    mismo "prev" y la última escritura perdía el ajuste de la otra (lost
    update). La prueba verifica que el SELECT de inventario lleve FOR UPDATE.
    """

    def _capturar_sql(self, func, *args, **kwargs):
        from sqlalchemy import event

        capturado = []

        def _listener(conn, cursor, statement, params, context, executemany):
            capturado.append(statement)

        event.listen(db.engine, "before_cursor_execute", _listener)
        try:
            func(*args, **kwargs)
        finally:
            event.remove(db.engine, "before_cursor_execute", _listener)
        return capturado

    @staticmethod
    def _bloquea_inventario(statements):
        return any(
            'FOR UPDATE' in s.upper() and 'FROM INVENTORY' in s.upper()
            for s in statements
        )

    def test_anular_compra_bloquea_la_fila_de_inventario(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('10.00'),
                                              Decimal('5.00'))])
        db.session.commit()
        sql = self._capturar_sql(self.repo.logical_annulment, compra.id,
                                 self.admin.id)
        self.assertTrue(self._bloquea_inventario(sql), sql)

    def test_editar_compra_bloquea_la_fila_de_inventario(self):
        compra = self.crear_compra(renglones=[(self.prod_a.id, Decimal('10.00'),
                                              Decimal('5.00'))])
        detalle_id = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).one().id
        db.session.commit()
        items = [self.item(detalle_id, quantity=8, foreign_price=5)]
        sql = self._capturar_sql(self.repo.logical_edit, compra.id,
                                 self.admin.id, items, "ajuste")
        self.assertTrue(self._bloquea_inventario(sql), sql)

    def test_registro_compra_bloquea_la_fila_de_inventario(self):
        from app.logistics.services.purchase_service import PurchaseService

        data = {
            'currency': 'USD',
            'exchange_rate': '10.0000',
            'supplier_id': self.proveedor.id,
            'user_id': self.admin.id,
            'invoice_url': 'f.pdf',
            'items': [{
                'product_id': self.prod_a.id,
                'quantity': 5,
                'foreign_price': 25,
                'lot_number': 'L-BLOQ-1',
                'expiration_date': None,
            }],
        }
        resultado = {}
        sql = self._capturar_sql(
            lambda: resultado.update(PurchaseService.register_purchase(data)))
        self.assertTrue(resultado.get('success'), resultado)
        self.assertTrue(self._bloquea_inventario(sql), sql)


if __name__ == '__main__':
    unittest.main()
