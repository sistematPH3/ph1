"""Pruebas de la regla: sin factura subida no se registra ninguna compra.

La foto viaja a ImgBB de forma sincrona ANTES de crear la compra, de modo que
no existen compras nuevas con `invoice_url` en estados intermedios como
"En proceso..." o "Comprobante no guardado".
"""
import io
import os
import unittest
from unittest import mock

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

from PIL import Image  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import (Inventory, Location, Product, Purchase,  # noqa: E402
                        PurchaseAuditLog, PurchaseDetail, Role, Supplier,
                        User)
from app.integrations.imgbb import imgbb_services  # noqa: E402
from app.logistics.routes import purchase_routes as rutas  # noqa: E402

TEXTO_FACTURA = [
    'FACTURA',
    'DISTRIBUIDORA LA PIÑA, C.A.',
    'RIF: J-30123456-7',
    'Nro de control: 00-00123',
    'Fecha: 20/11/2026',
    'TOTAL A PAGAR: 100,00',
]

URL_IMGBB = 'https://i.ibb.co/prueba/factura.jpg'


def imagen_bytes(ancho=1200, alto=1600):
    buffer = io.BytesIO()
    Image.new('RGB', (ancho, alto), (245, 245, 245)).save(buffer, format='JPEG')
    return buffer.getvalue()


class CompraConComprobanteTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

        self.rol = Role(name='Administrator')
        db.session.add(self.rol)
        db.session.flush()

        self.sede = db.session.get(Location, 1)
        if not self.sede:
            self.sede = Location(id=1, name='Principal', state='VE',
                                 is_active=True)
            db.session.add(self.sede)

        self.admin = User(name='Admin Foto', email='foto@ph.test',
                          password_hash='x', role_id=self.rol.id,
                          is_active=True)
        self.proveedor = Supplier(name='Proveedor Foto', tax_id='J-FOTO',
                                  status='ACTIVE')
        self.producto = Product(name='Harina Foto', sku='FOTO-1',
                                unit_of_measure='KG', is_active=True,
                                min_stock=1)
        db.session.add_all([self.admin, self.proveedor, self.producto])
        db.session.commit()

        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.admin.id)
            sesion['_fresh'] = True

        self.subidas = []
        self._parches = [
            mock.patch.object(rutas, 'leer_texto',
                              lambda imagen, usar_orientacion=False:
                              (list(TEXTO_FACTURA), None)),
            mock.patch.object(rutas, '_ESPERA_REINTENTO_SUBIDA', 0),
        ]
        for parche in self._parches:
            parche.start()

    def tearDown(self):
        for parche in reversed(self._parches):
            parche.stop()
        db.session.rollback()
        for tabla in reversed(db.metadata.sorted_tables):
            db.session.execute(tabla.delete())
        db.session.commit()
        self.ctx.pop()

    def _subir(self, memoria):
        self.subidas.append(memoria.read())
        return URL_IMGBB

    def _registrar(self, contenido, token=None):
        datos = {
            'supplier_id': str(self.proveedor.id),
            'currency': 'EUR',
            'exchange_rate': '40,00',
            'user_id': str(self.admin.id),
            'product_id[]': str(self.producto.id),
            'quantity[]': '2',
            'lot_number[]': 'LOTE-FOTO',
            'expiration_date[]': '2027-01-31',
            'foreign_price[]': ['100,00'],
            'invoice_photo': (io.BytesIO(contenido), 'factura.jpg'),
        }
        if token:
            datos['submit_token'] = token
        return self.client.post('/logistics/purchases', data=datos,
                                content_type='multipart/form-data')

    def _conteos(self):
        return {
            'compras': db.session.query(Purchase).count(),
            'detalles': db.session.query(PurchaseDetail).count(),
            'auditoria': db.session.query(PurchaseAuditLog).count(),
            'inventario': db.session.query(Inventory).count(),
        }

    def test_el_registro_exitoso_guarda_la_url_definitiva(self):
        foto = imagen_bytes()
        with mock.patch.object(rutas, 'upload_invoice_image', self._subir):
            respuesta = self._registrar(foto)
            self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
            db.session.expire_all()
            compra = db.session.get(Purchase,
                                    respuesta.get_json()['purchase_id'])

        self.assertEqual(compra.invoice_url, URL_IMGBB,
                         'La compra no nació con su URL definitiva')
        self.assertEqual(compra.status, 'COMPLETED')
        self.assertEqual(len(self.subidas), 1)
        self.assertGreater(len(self.subidas[0]), 0,
                           'La subida recibió un archivo vacío')
        self.assertEqual(self.subidas[0], foto,
                         'Los bytes subidos no son la foto original')
        stock = db.session.query(Inventory).filter_by(
            location_id=1, product_id=self.producto.id).first()
        self.assertEqual(float(stock.current_quantity), 2.0)

    def test_el_detalle_muestra_el_comprobante_recien_registrado(self):
        with mock.patch.object(rutas, 'upload_invoice_image', self._subir):
            respuesta = self._registrar(imagen_bytes())
            self.assertEqual(respuesta.status_code, 201, respuesta.get_json())

        detalle = self.client.get(
            f"/logistics/purchases/{respuesta.get_json()['purchase_id']}")
        self.assertEqual(detalle.status_code, 200)
        html = detalle.get_data(as_text=True)
        self.assertIn(URL_IMGBB, html)
        self.assertNotIn(rutas._MARCA_FALLO_SUBIDA, html)
        self.assertNotIn('En proceso...', html)

    def test_si_imgbb_falla_tras_los_reintentos_no_se_guarda_la_compra(self):
        intentos = []

        def sin_red(memoria):
            intentos.append(memoria.read())
            raise Exception('Fallo de conexión al intentar subir la evidencia')

        with mock.patch.object(rutas, 'upload_invoice_image', sin_red):
            with self.assertLogs(self.app.logger, level='ERROR') as registro:
                respuesta = self._registrar(imagen_bytes())

        self.assertEqual(respuesta.status_code, 502)
        cuerpo = respuesta.get_json()
        self.assertEqual(cuerpo['campo'], 'invoice_photo')
        self.assertIn('La compra no fue registrada', cuerpo['error'])

        self.assertEqual(
            self._conteos(),
            {'compras': 0, 'detalles': 0, 'auditoria': 0, 'inventario': 0},
            'El fallo de la foto dejó rastro en la base de datos')

        self.assertEqual(len(intentos), rutas._REINTENTOS_SUBIDA,
                         'No se agotaron los reintentos antes de rendirse')
        texto_log = '\n'.join(registro.output)
        self.assertIn('Fallo de conexión', texto_log)
        self.assertIn('No se registro ninguna compra', texto_log)

    def test_el_fallo_de_subida_libera_el_token_para_reintentar(self):
        token = 'token-fallo-de-subida'

        def sin_red(memoria):
            self.subidas.append(memoria.read())
            raise Exception('ImgBB caído')

        with mock.patch.object(rutas, 'upload_invoice_image', sin_red):
            primero = self._registrar(imagen_bytes(), token=token)
        self.assertEqual(primero.status_code, 502)
        self.assertEqual(self._conteos()['compras'], 0)

        with mock.patch.object(rutas, 'upload_invoice_image', self._subir):
            segundo = self._registrar(imagen_bytes(), token=token)
        self.assertEqual(segundo.status_code, 201, segundo.get_json())
        db.session.expire_all()
        compra = db.session.get(Purchase, segundo.get_json()['purchase_id'])
        self.assertEqual(compra.invoice_url, URL_IMGBB)
        self.assertEqual(self._conteos()['compras'], 1,
                         'El reintento con el mismo token no guardó la compra')

    def test_un_fallo_transitorio_no_impide_la_compra(self):
        intentos = []

        def falla_una_vez(memoria):
            intentos.append(memoria.read())
            if len(intentos) == 1:
                raise Exception('Timeout de ImgBB')
            return 'https://i.ibb.co/prueba/reintentada.jpg'

        with mock.patch.object(rutas, 'upload_invoice_image', falla_una_vez):
            respuesta = self._registrar(imagen_bytes())
        self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
        self.assertEqual(len(intentos), 2)
        self.assertGreater(len(intentos[1]), 0,
                           'El reintento envió un archivo vacío')
        db.session.expire_all()
        compra = db.session.get(Purchase, respuesta.get_json()['purchase_id'])
        self.assertEqual(compra.invoice_url,
                         'https://i.ibb.co/prueba/reintentada.jpg')

    def test_una_subida_sin_url_no_guarda_la_compra(self):
        for valor in (None, '', 'Fallo de red sin URL'):
            with self.subTest(valor=valor):
                with mock.patch.object(
                        rutas, 'upload_invoice_image',
                        lambda memoria, v=valor: v):
                    respuesta = self._registrar(imagen_bytes())
                self.assertEqual(respuesta.status_code, 502)
                self.assertEqual(respuesta.get_json()['campo'], 'invoice_photo')
                self.assertEqual(
                    self._conteos(),
                    {'compras': 0, 'detalles': 0, 'auditoria': 0,
                     'inventario': 0},
                    'Una subida sin URL dejo rastro en la base de datos')

    def test_un_error_controlado_del_servicio_libera_el_token(self):
        token = 'token-servicio-falla'
        fallo = {'success': False,
                 'error': 'No se pudo registrar la compra.'}

        with mock.patch.object(rutas, 'upload_invoice_image', self._subir), \
                mock.patch.object(rutas.PurchaseService, 'register_purchase',
                                  return_value=fallo):
            primero = self._registrar(imagen_bytes(), token=token)
        self.assertEqual(primero.status_code, 500)
        self.assertEqual(self._conteos()['compras'], 0)

        with mock.patch.object(rutas, 'upload_invoice_image', self._subir):
            segundo = self._registrar(imagen_bytes(), token=token)
        self.assertEqual(segundo.status_code, 201, segundo.get_json())
        self.assertEqual(self._conteos()['compras'], 1,
                         'El fallo del servicio dejo el token bloqueado')

    def test_una_respuesta_que_no_es_url_no_guarda_la_compra(self):
        with mock.patch.object(rutas, 'upload_invoice_image',
                               lambda memoria: rutas._MARCA_FALLO_SUBIDA):
            respuesta = self._registrar(imagen_bytes())

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(respuesta.get_json()['campo'], 'invoice_photo')
        self.assertEqual(self._conteos()['compras'], 0,
                         'Se guardó una compra con la marca de fallo como URL')

    def test_reenviar_el_mismo_token_tras_el_exito_no_duplica_la_compra(self):
        token = 'token-idempotente-subida'
        with mock.patch.object(rutas, 'upload_invoice_image', self._subir):
            primero = self._registrar(imagen_bytes(), token=token)
            segundo = self._registrar(imagen_bytes(), token=token)

        self.assertEqual(primero.status_code, 201)
        self.assertEqual(segundo.status_code, 201)
        self.assertEqual(segundo.get_json()['purchase_id'],
                         primero.get_json()['purchase_id'])
        self.assertEqual(self._conteos()['compras'], 1)
        self.assertEqual(len(self.subidas), 1,
                         'El reenvío volvió a subir la misma factura')


class SubidaImgbbTest(unittest.TestCase):
    """La petición a ImgBB debe viajar con nombre, formato y error real."""

    def test_envia_el_archivo_con_extension_y_tipo_mime(self):
        contenido = imagen_bytes(600, 400)
        memoria = io.BytesIO(contenido)
        memoria.filename = 'factura.jpg'

        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {
            'success': True, 'data': {'url': 'https://i.ibb.co/x/factura.jpg'}}

        with mock.patch.dict(os.environ, {'IMGBB_API_KEY': 'clave-de-prueba'}):
            with mock.patch.object(imgbb_services.requests, 'post',
                                   return_value=respuesta) as post:
                url = imgbb_services.upload_invoice_image(memoria)

        self.assertEqual(url, 'https://i.ibb.co/x/factura.jpg')
        enviado = post.call_args.kwargs['files']['image']
        self.assertEqual(enviado[0], 'factura.jpg')
        self.assertEqual(enviado[1], contenido)
        self.assertEqual(enviado[2], 'image/jpeg')
        self.assertEqual(post.call_args.kwargs['data']['key'], 'clave-de-prueba')

    def test_expone_el_motivo_real_cuando_imgbb_rechaza_la_imagen(self):
        memoria = io.BytesIO(imagen_bytes(600, 400))
        memoria.filename = 'factura.png'

        respuesta = mock.Mock(status_code=400)
        respuesta.json.return_value = {
            'success': False,
            'error': {'message': 'Invalid image'}}

        with mock.patch.dict(os.environ, {'IMGBB_API_KEY': 'clave-de-prueba'}):
            with mock.patch.object(imgbb_services.requests, 'post',
                                   return_value=respuesta):
                with self.assertRaises(Exception) as error:
                    imgbb_services.upload_invoice_image(memoria)

        self.assertIn('Invalid image', str(error.exception))
        self.assertIn('400', str(error.exception))


if __name__ == '__main__':
    unittest.main()
