"""
Pruebas de los numeros del registro de compra.

Cubre el bug mas grave que se encontro al auditar: el navegador y el servidor
NO eran simetricos al normalizar numeros.

El formulario usa type="text" inputmode="decimal", asi que el usuario escribe
la coma decimal venezolana. parseNum() en el JS la resuelve bien, pero luego
mandaba String(numero), que usa PUNTO: "10.335". El servidor volvia a
interpretar ese punto como separador de miles y devolvia 10335. Un error
silencioso de 1000x en precios, cantidades y tasa de cambio, sin que nada
fallara: la compra se guardaba y el stock se descontaba igual.
"""
import os
import re
import unittest
from decimal import Decimal

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _asegurar_bd_pruebas():
    """
    Comprueba la base de pruebas conectandose a ella, sin consultar el
    catalogo de PostgreSQL: leer pg_database resultaba intermitente en este
    entorno y hacia fallar la importacion del modulo entero. Si la base no
    existe, PostgreSQL dice exactamente cual falta y se crea; si el problema
    es otro, las pruebas de abajo lo dicen con su propio mensaje.
    """
    engine = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return
    except Exception:
        pass
    finally:
        engine.dispose()

    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine_admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine_admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    finally:
        engine_admin.dispose()



_asegurar_bd_pruebas()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db  # noqa: E402
from app.logistics.requests.purchase_validators import normalizar_numero  # noqa: E402


def parse_num_como_el_navegador(valor):
    """Replica exacta de parseNum() de register_purchase.js."""
    s = re.sub(r'\s+', '', str(valor).strip())
    signo = ''
    if s.startswith('-'):
        signo = '-'
        s = s[1:]
    if ',' in s:
        norm = s.replace('.', '').replace(',', '.', 1)
    elif re.match(r'^0+\.\d+$', s):
        norm = s
    else:
        norm = re.sub(r'\.(?=\d{3}(?!\d))', '', s)
    return float(signo + norm)


def como_string_js(numero):
    """String(numero) en JavaScript: la forma en que viaja al servidor."""
    if numero == int(numero):
        return str(int(numero))
    return repr(numero)


class TestSimetriaNavegadorServidor(unittest.TestCase):
    """
    El formulario manda el TEXTO que el usuario escribio y el servidor aplica
    la convencion venezolana una sola vez: el punto separa miles y la coma
    separa decimales.

    El bug era que el navegador parseaba y reformataba antes de enviar: "10,335"
    (diez con trescientos treinta y cinco) salia como "10.335" y el servidor leia
    ese punto como separador de miles, guardando 10335. Un error de 1000x
    silencioso, sin que ninguna validacion se quejara: la compra se guardaba y
    el stock se descontaba igual.
    """

    def _round_trip(self, escrito):
        # Lo que hace el servidor con lo que el usuario escribio.
        return float(normalizar_numero(escrito))

    def test_coma_es_decimal(self):
        for escrito, esperado in (("10,335", 10.335), ("12,345", 12.345),
                                  ("5,125", 5.125), ("1,5", 1.5),
                                  ("12,75", 12.75), ("0,500", 0.5)):
            with self.subTest(escrito=escrito):
                self.assertAlmostEqual(self._round_trip(escrito), esperado)

    def test_punto_es_miles(self):
        for escrito, esperado in (("1.500", 1500.0), ("10.335", 10335.0),
                                  ("1.234,56", 1234.56), ("2.000.000", 2000000.0)):
            with self.subTest(escrito=escrito):
                self.assertAlmostEqual(self._round_trip(escrito), esperado)

    def test_cero_con_punto_es_decimal(self):
        # Nadie escribe 0.500 para querer 500.
        self.assertEqual(float(normalizar_numero("0.500")), 0.5)
        self.assertEqual(float(normalizar_numero("0.050")), 0.05)

    def test_caso_original_reportado(self):
        # El valor concreto que delato el bug: 10,335 llegaba como 10.335.
        self.assertAlmostEqual(float(normalizar_numero("10,335")), 10.335)

    def test_el_formulario_no_reinterpreta_antes_de_enviar(self):
        """
        Guarda de regresion del Javascript: si vuelve a llamar numeroLimpio()
        al enviar, el punto del navegador rompe la convencion del servidor.
        """
        import os
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()

        inicio = codigo.index("addEventListener('submit'")
        # La ventana es holgada a proposito: entre el inicio del manejador y
        # los append hay codigo de la proteccion contra el doble envio y del
        # manejo de respuestas no JSON. Con una ventana justa, anadir una
        # guarda de seguridad mas rompia esta prueba sin que hubiera ningun
        # cambio en lo que el submit envia.
        bloque = codigo[inicio:inicio + 4000]
        for campo in ('quantity[]', 'foreign_price[]', 'exchange_rate'):
            self.assertIn(f"formData.append('{campo}'", bloque)
        self.assertNotIn('numeroLimpio(', bloque,
                         "El submit no debe reparsear: manda el texto del campo")


class TestPrecioEnBolivares(unittest.TestCase):
    """
    price_bs se cuantiza a 2 decimales, igual que en la edicion de compras.
    Antes el registro mandaba el producto sin redondear y la columna
    Numeric(15,2) lo truncaba en el servidor: registrar y luego editar una
    compra dcia dos numeros distintos para el mismo dato.
    """

    @classmethod
    def setUpClass(cls):
        from app.models import (Location, Product, Role, Supplier, User,
                                ProductType, Category)
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            rol = db.session.query(Role).first()
            if not rol:
                rol = Role(name="admin")
                db.session.add(rol)
                db.session.flush()
            cls.usuario_id = rol.id
            usuario = db.session.query(User).filter_by(email="numeros@local").first()
            if not usuario:
                usuario = User(name="Numeros", email="numeros@local",
                               password_hash="x", role_id=rol.id, is_active=True)
                db.session.add(usuario)
                db.session.flush()
            cls.uid = usuario.id
            ubicacion = db.session.get(Location, 1)
            if not ubicacion:
                db.session.add(Location(id=1, name="Almacen Central",
                                        state="VE", is_active=True))
                db.session.flush()
            proveedor = db.session.query(Supplier).filter_by(
                tax_id="J-11111111-1").first()
            if not proveedor:
                proveedor = Supplier(name="Proveedor Numeros",
                                     tax_id="J-11111111-1", status="ACTIVE")
                db.session.add(proveedor)
                db.session.flush()
            cls.proveedor_id = proveedor.id
            producto = db.session.query(Product).filter_by(sku="NUMTEST1").first()
            if not producto:
                categoria = db.session.query(Category).first()
                if not categoria:
                    categoria = Category(name="NumTest")
                    db.session.add(categoria)
                    db.session.flush()
                tipo = db.session.query(ProductType).filter_by(
                    name="PTNumTest").first()
                if not tipo:
                    tipo = ProductType(name="PTNumTest", category_id=categoria.id)
                    db.session.add(tipo)
                    db.session.flush()
                producto = Product(name="Producto Numerico", sku="NUMTEST1",
                                   product_type_id=tipo.id, is_active=True)
                db.session.add(producto)
                db.session.flush()
            cls.producto_id = producto.id
            db.session.commit()

    def setUp(self):
        from app.models import Purchase
        ctx = self.app.app_context()
        ctx.push()
        self._ctx = ctx
        self._purchase_ids = [p.id for p in db.session.query(Purchase).all()]

    def tearDown(self):
        from app.models import (Purchase, PurchaseDetail, PurchaseAuditLog,
                                Inventory)
        nuevos = [p.id for p in db.session.query(Purchase).all()
                  if p.id not in self._purchase_ids]
        for pid in nuevos:
            # El log de auditoria tiene FK a la compra: va primero o el
            # borrado de la compra viola la restriccion.
            db.session.query(PurchaseAuditLog).filter_by(
                purchase_id=pid).delete(synchronize_session=False)
            db.session.query(PurchaseDetail).filter_by(
                purchase_id=pid).delete(synchronize_session=False)
            # El registro tambien suma existencias: sin borrarlo, las
            # pruebas dejaban el stock del producto inflado.
            db.session.query(Inventory).filter_by(
                product_id=self.producto_id).delete(synchronize_session=False)
            db.session.query(Purchase).filter_by(id=pid).delete()
        db.session.rollback()
        self._ctx.pop()

    def test_no_hay_error_de_mil_en_el_precio_unitario(self):
        from app.logistics.services.purchase_service import PurchaseService
        from app.models import Purchase, PurchaseDetail

        resultado = PurchaseService.register_purchase({
            'supplier_id': self.proveedor_id,
            'currency': 'USD',
            'exchange_rate': '36,5',
            'user_id': self.uid,
            'invoice_url': 'x',
            'items': [{
                'product_id': self.producto_id,
                'quantity': '3',
                # El total de la linea son 10,335 dolares: 3,445 por unidad.
                # Se manda la coma porque es lo que el usuario escribio; el
                # navegador ya no lo reescribe como "10.335".
                'foreign_price': '10,335',
                'expiration_date': None,
                'lot_number': 'LNUM1',
            }],
        })
        self.assertTrue(resultado['success'], resultado.get('message'))

        compra = db.session.get(Purchase, resultado['purchase_id'])
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).first()

        self.assertEqual(Decimal(str(detalle.foreign_price)), Decimal('3.45'),
                         "El precio unitario salio multiplicado por 1000")
        self.assertEqual(Decimal(str(compra.total_amount)), Decimal('10.34'),
                         "El total de la compra quedo corrupto")
        # 3.45 x 36.5 = 125.925 -> 125.93 con redondeo half-up a 2 decimales.
        self.assertEqual(Decimal(str(detalle.price_bs)), Decimal('125.93'))

    def test_en_bolivares_no_se_vuelve_a_multiplicar_por_la_tasa(self):
        """
        En Bs el importe ya es bolívares. Si se multiplicara otra vez por la
        tasa, 3.000 Bs se guardarian como 109.536,90 Bs.
        """
        from app.models import Purchase, PurchaseDetail
        from app.logistics.services.purchase_service import PurchaseService

        resultado = PurchaseService.register_purchase({
            'supplier_id': self.proveedor_id,
            'currency': 'BS',
            'exchange_rate': '36,5123',
            'user_id': self.uid,
            'invoice_url': 'x',
            'items': [{
                'product_id': self.producto_id,
                'quantity': '1',
                'foreign_price': '3.000',
                'expiration_date': None,
                'lot_number': 'LBS1',
            }],
        })
        self.assertTrue(resultado['success'], resultado.get('message'))

        compra = db.session.get(Purchase, resultado['purchase_id'])
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).first()

        self.assertEqual(Decimal(str(detalle.foreign_price)), Decimal('3000.00'))
        self.assertEqual(Decimal(str(detalle.price_bs)), Decimal('3000.00'),
                         "En Bs el precio en bolivares no se multiplica por la tasa")
        self.assertEqual(Decimal(str(compra.total_amount)), Decimal('3000.00'))

    def test_el_total_es_la_suma_de_las_lineas(self):
        """
        El total de la compra es la suma de los campos "Total Linea", que es lo
        que el resumen en pantalla muestra. Si el servidor hiciera otra cosa, el
        numero que ve el usuario antes de guardar no seria el que se guarda.
        """
        from app.models import Purchase
        from app.logistics.services.purchase_service import PurchaseService

        resultado = PurchaseService.register_purchase({
            'supplier_id': self.proveedor_id,
            'currency': 'USD',
            'exchange_rate': '36,5123',
            'user_id': self.uid,
            'invoice_url': 'x',
            'items': [
                {'product_id': self.producto_id, 'quantity': '2',
                 'foreign_price': '100,50', 'expiration_date': None,
                 'lot_number': 'LA1'},
                {'product_id': self.producto_id, 'quantity': '3',
                 'foreign_price': '250,25', 'expiration_date': None,
                 'lot_number': 'LA2'},
            ],
        })
        self.assertTrue(resultado['success'], resultado.get('message'))

        compra = db.session.get(Purchase, resultado['purchase_id'])
        # 100,50 + 250,25 = 350,75. Las cantidades (2 y 3) no multiplican.
        self.assertEqual(Decimal(str(compra.total_amount)), Decimal('350.75'))

    def test_price_bs_siempre_tiene_dos_decimales(self):
        from app.logistics.services.purchase_service import PurchaseService
        from app.models import Purchase, PurchaseDetail

        resultado = PurchaseService.register_purchase({
            'supplier_id': self.proveedor_id,
            'currency': 'USD',
            'exchange_rate': '36.5123456789',
            'user_id': self.uid,
            'invoice_url': 'x',
            'items': [{
                'product_id': self.producto_id,
                'quantity': 7,
                'foreign_price': '13.77',
                'expiration_date': None,
                'lot_number': 'LNUM2',
            }],
        })
        self.assertTrue(resultado['success'], resultado.get('message'))

        compra = db.session.get(Purchase, resultado['purchase_id'])
        detalle = db.session.query(PurchaseDetail).filter_by(
            purchase_id=compra.id).first()

        self.assertEqual(detalle.price_bs.as_tuple().exponent, -2,
                         "price_bs debe venir cuantizado a 2 decimales")
        self.assertEqual(compra.total_amount.as_tuple().exponent, -2)

    def test_un_error_no_revela_el_sql_al_cliente(self):
        """
        La excepcion de psycopg2 incluye la sentencia completa y sus
        parametros. Antes se devolvia tal cual dentro de 'message'.
        """
        from app.logistics.services.purchase_service import PurchaseService

        resultado = PurchaseService.register_purchase({
            'supplier_id': 999999,          # no existe
            'currency': 'USD',
            'exchange_rate': '36.5',
            'user_id': self.uid,
            'invoice_url': 'x',
            'items': [{
                'product_id': self.producto_id,
                'quantity': 1,
                'foreign_price': '5',
                'expiration_date': None,
                'lot_number': 'LNUM3',
            }],
        })

        self.assertFalse(resultado['success'])
        texto = ' '.join(str(v) for v in resultado.values())
        for prohibido in ('INSERT INTO', 'SELECT ', 'psycopg2', 'ForeignKey'):
            self.assertNotIn(prohibido, texto,
                             f"El detalle interno {prohibido!r} se filtro al cliente")
        self.assertNotIn('999999', texto)
