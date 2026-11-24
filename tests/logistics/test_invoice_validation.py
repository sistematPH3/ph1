"""Pruebas de la validacion de la foto de factura en el registro de compra.

Cubre lo corregido:
- la foto no se validaba en absoluto: cualquier archivo de cualquier tamano
  pasaba y se leia entero a la memoria,
- el nombre del archivo viajaba crudo hacia el hosting externo,
- no se distinguia una factura de proveedor de un comprobante de tarjeta,
  que son los dos documentos validos en una pizzeria,
- el hilo de subida se tragaba la excepcion y dejaba la compra colgada.
"""
import io
import os
import time
import unittest

from PIL import Image
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _asegurar_bd_pruebas():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not existe:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_asegurar_bd_pruebas()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402
from app.logistics.requests.purchase_validators import (  # noqa: E402
    PATRON_RIF,
    PurchaseValidator,
    evaluar_comprobante,
)
from app.integrations.ocr.ocr_services import limpiar_para_evaluar  # noqa: E402


def imagen_bytes(ancho=1200, alto=1600, formato='JPEG', color=(240, 240, 240)):
    buffer = io.BytesIO()
    Image.new('RGB', (ancho, alto), color).save(buffer, format=formato)
    return buffer.getvalue()


def adjunto(contenido, nombre='factura.jpg', content_type='image/jpeg'):
    return FileStorage(
        stream=io.BytesIO(contenido),
        filename=nombre,
        content_type=content_type,
    )


def _sin_acentos(texto):
    import unicodedata
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto or '')
        if not unicodedata.combining(c)
    ).lower()


# Texto real devuelto por RapidOCR sobre una foto de comprobante de tarjeta.
TEXTO_COMPROBANTE_TARJETA = [
    "BANCO DE VENEZUELA", "RECIBO DE COMPRA", "TORRES MUNOZ ANTONIO J",
    "MASTER DEBITO", "CARACAS", "RIF:V-186754804", "TERM:00001002",
    "541105******4929 (I)", "LOTE NO:001131", "FECHA/HORA: 2026/09/2713:33:41",
    "TRACE:000805", "APROB:333052", "Monto: Bs. 18.925.00", "AID:A0000000041010",
    "APROBADA", "NO REUQIERE FIRMA",
    "ME OBLIGO A PAGAR AL BANCO EMISOR DE ESTA TARJETA EL MONTO DE ESTA NOTA DE CONSUMO",
]

# Una factura de proveedor Tips: es sintetica, la lectura real de una factura
# fiscal Habria que confirmarla cuando se tenga una foto de ese tipo.
TEXTO_FACTURA_PROVEEDOR = """
COMERCIALIZADORA DE ALIMENTOS C.A.
RIF: J-31245678-9
NRO. DE FACTURA: 000123
N CONTROL: 00045678
FACTURA
Proveedor: Comercializadora de Alimentos C.A.
Fecha: 27/09/2026
HARINA 000 x 50kg  10  25,00  250,00
BASE IMPONIBLE  250,00
IVA 16%  40,00
IGTF 0,75%  2,18
TOTAL  292,18
Bs. 292,18
"""


class TestValidacionImagen(unittest.TestCase):
    """Que la foto sea realmente una imagen utilizable."""

    def test_acepta_una_foto_normal(self):
        es_valida, error, info = PurchaseValidator.validate_invoice_image(
            adjunto(imagen_bytes())
        )
        self.assertTrue(es_valida, error)
        self.assertEqual(info['formato'], 'JPEG')
        self.assertEqual(info['extension'], '.jpg')
        self.assertEqual((info['ancho'], info['alto']), (1200, 1600))

    def test_una_foto_de_celular_se_reduce_antes_del_ocr(self):
        es_valida, error, info = PurchaseValidator.validate_invoice_image(
            adjunto(imagen_bytes(ancho=3000, alto=4000))
        )
        self.assertTrue(es_valida, error)
        self.assertEqual((info['ancho'], info['alto']), (3000, 4000))
        self.assertEqual(max(info['imagen_ocr'].size), 800)
        self.assertEqual(info['imagen_ocr'].size, (600, 800))

    def test_una_foto_de_celular_se_endereza_por_su_exif(self):
        buffer = io.BytesIO()
        original = Image.new('RGB', (400, 800), (250, 250, 250))
        exif = original.getexif()
        exif[274] = 6
        original.save(buffer, format='JPEG', exif=exif)
        es_valida, error, info = PurchaseValidator.validate_invoice_image(
            adjunto(buffer.getvalue())
        )
        self.assertTrue(es_valida, error)
        self.assertEqual(info['imagen_ocr'].size, (800, 400))

    def test_rechaza_si_no_hay_archivo(self):
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(None)
        self.assertFalse(es_valida)
        self.assertIn('adjuntar', error.lower())

    def test_rechaza_un_ejecutable_disfrazado(self):
        """El content_type dice jpg, pero el contenido es un ZIP/EXE."""
        falso = b'PK\x03\x04\x00\x00\x08\x00' + b'\x00' * 500
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(falso, nombre='factura.jpg', content_type='image/jpeg')
        )
        self.assertFalse(es_valida, "Un .exe renombrado a .jpg no puede pasar")
        self.assertIn('imagen', error.lower())

    def test_rechaza_un_pdf(self):
        pdf = b'%PDF-1.4\n' + b'0' * 400
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(pdf, nombre='factura.pdf', content_type='application/pdf')
        )
        self.assertFalse(es_valida)

    def test_rechaza_archivo_vacio(self):
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(b'', nombre='factura.jpg')
        )
        self.assertFalse(es_valida)
        self.assertIn('vacia', _sin_acentos(error))

    def test_rechaza_archivo_demasiado_grande(self):
        grande = imagen_bytes(ancho=4000, alto=4000) + b'\x00' * (9 * 1024 * 1024)
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(grande)
        )
        self.assertFalse(es_valida, "Sin tope de tamano, un adjunto enorme tumba el servidor")
        self.assertIn('mb', error.lower())

    def test_rechaza_imagen_demasiado_pequena(self):
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(imagen_bytes(ancho=64, alto=64))
        )
        self.assertFalse(es_valida, "Un icono no sirve como evidencia")
        self.assertIn('pequena', _sin_acentos(error))

    def test_rechaza_ruido_sustancial_en_la_imagen(self):
        """
        Image.verify() se queda con la cabecera y lo aprueba; la decodificacion
        completa si lo detecta. Por eso se hace la segunda pasada.
        """
        contenido = bytearray(imagen_bytes(ancho=1400, alto=1800))
        contenido[300:1200] = bytes(range(256)) * 3  # datos comprimidos alterados
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(bytes(contenido))
        )
        self.assertFalse(es_valida, "Una imagen con los datos rotos no sirve")
        self.assertTrue(
            'imagen' in _sin_acentos(error) or 'incompleta' in _sin_acentos(error),
            f"El mensaje debe explicar el rechazo, no ser generico: {error}",
        )

    def test_rechaza_datos_no_comprimidos_con_cabecera_falsa(self):
        """Cabecera JPEG real y luego basura: eso si es un archivo falso."""
        completa = imagen_bytes(ancho=1400, alto=1800)
        cabecera = completa[:2]
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(cabecera + b'\x00' * 5000)
        )
        self.assertFalse(es_valida, "Una cabecera sin datos de imagen no vale")

    def test_rechaza_imagen_cortada(self):
        """Subida interrumpida: Pillow.verify() la aprueba, esta comprobacion no."""
        completa = imagen_bytes(ancho=1400, alto=1800)
        cortada = completa[: int(len(completa) * 0.6)]
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(cortada)
        )
        self.assertFalse(es_valida, "Una imagen a medias no sirve de evidencia")

    def test_acepta_png_y_webp(self):
        for formato in ('PNG', 'WEBP'):
            with self.subTest(formato=formato):
                es_valida, error, info = PurchaseValidator.validate_invoice_image(
                    adjunto(imagen_bytes(formato=formato), nombre=f'f.{formato.lower()}')
                )
                self.assertTrue(es_valida, error)
                self.assertEqual(info['formato'], formato)

    def test_acepta_gif_animado_no_permitido(self):
        """El alcance son fotos: formatos como GIF quedan fuera."""
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(imagen_bytes(formato='GIF'), nombre='f.gif')
        )
        self.assertFalse(es_valida)
        self.assertIn('gif', error.lower())


class TestReglasDeComprobante(unittest.TestCase):
    """Distinguir factura de proveedor de comprobante de tarjeta."""

    def test_comprobante_de_tarjeta_se_acepta(self):
        """Foto real de prueba: papel del punto de venta."""
        texto = limpiar_para_evaluar(TEXTO_COMPROBANTE_TARJETA)
        r = evaluar_comprobante(texto)
        self.assertEqual(r['tipo'], 'comprobante_tarjeta')
        self.assertTrue(r['puede_aceptar'], f"debio aceptarse, dio {r}")

    def test_factura_de_proveedor_se_acepta(self):
        texto = limpiar_para_evaluar(TEXTO_FACTURA_PROVEEDOR.splitlines())
        r = evaluar_comprobante(texto)
        self.assertEqual(r['tipo'], 'factura_proveedor')
        self.assertTrue(r['puede_aceptar'], f"debio aceptarse, dio {r}")

    def test_foto_de_producto_no_se_acepta(self):
        texto = "wholesale product premium quality best price contact us high quality for your store"
        r = evaluar_comprobante(texto)
        self.assertFalse(r['puede_aceptar'])
        self.assertEqual(r['tipo'], 'desconocido')

    def test_texto_vacio_es_ilegible(self):
        r = evaluar_comprobante("")
        self.assertFalse(r['puede_aceptar'])
        # Ilegible no es lo mismo que 'no es factura': la foto estaba mala.
        self.assertEqual(r['veredicto'], 'ilegible')

    def test_solo_un_rif_no_alcanza(self):
        r = evaluar_comprobante("J-31245678-9")
        self.assertFalse(r['puede_aceptar'], "Un RIF suelto no es una factura")

    def test_umbral_alto_rechaza_tarjeta_debilis(self):
        texto = limpiar_para_evaluar(["RECIBO DE COMPRA", "BANCO DE VENEZUELA"])
        r = evaluar_comprobante(texto, umbral=99)
        self.assertFalse(r['puede_aceptar'], "El umbral debe poder endurecerse")

    def test_el_rif_real_de_la_foto_se_reconoce(self):
        """El patron anterior exigia un guion antes del ultimo digito y fallaba."""
        for rif in ('V-186754804', 'J-31245678-9', 'J-31245678-9', 'G-20000000-1'):
            with self.subTest(rif=rif):
                self.assertIsNotNone(
                    PATRON_RIF.search(rif),
                    f"El RIF {rif} debe reconocerse",
                )

    def test_el_rif_en_minusculas_suma_puntos(self):
        self.assertIsNotNone(PATRON_RIF.search('rif: j-31245678-9'))
        texto = limpiar_para_evaluar([
            'FACTURA', 'PROVEEDOR: COMERCIALIZADORA C.A.',
            'RIF: J-31245678-9', 'SUBTOTAL 100,00', 'TOTAL 116,00',
        ])
        r = evaluar_comprobante(texto)
        self.assertIn('rif', r['marcas'])
        self.assertTrue(r['puede_aceptar'], f"debio aceptarse, dio {r}")

    def test_un_carnet_venezolano_se_rechaza_siempre(self):
        texto = limpiar_para_evaluar([
            'REPUBLICA BOLIVARIANA DE VENEZUELA',
            'CEDULA DE IDENTIDAD',
            'V-18.675.480',
            'FECHA DE NACIMIENTO: 12/03/1990',
            'NACIONALIDAD: VENEZOLANA', 'ESTADO CIVIL: SOLTERO',
        ])
        r = evaluar_comprobante(texto)
        self.assertFalse(r['puede_aceptar'], f"un carnet no es una factura: {r}")
        self.assertEqual(r['tipo'], 'documento_identidad')
        self.assertIn('documento de identidad', r['detalle'])

    def test_bolivariana_no_activa_el_marcador_iva(self):
        from app.logistics.requests.purchase_validators import (
            MARCAS_FACTURA, _cuantas_marcas_encuentra,
        )
        marcas = _cuantas_marcas_encuentra(
            'republica bolivariana de venezuela', MARCAS_FACTURA)
        self.assertNotIn('subtotal_iva', marcas)


class TestMensajeAlUsuario(unittest.TestCase):
    """El usuario tiene que enterarse si su foto no era un comprobante."""

    def test_mensaje_de_factura_aceptada(self):
        from app.logistics.routes.purchase_routes import _mensaje_factura

        texto = _mensaje_factura(
            {'puede_aceptar': True, 'tipo': 'factura_proveedor'})
        self.assertIn('verificada', texto)
        self.assertNotIn('aviso', texto.lower())

    def test_mensaje_de_tarjeta_aceptada(self):
        from app.logistics.routes.purchase_routes import _mensaje_factura

        texto = _mensaje_factura(
            {'puede_aceptar': True, 'tipo': 'comprobante_tarjeta'})
        self.assertIn('tarjeta', texto.lower())

    def test_una_factura_aceptada_no_trae_advertencias(self):
        from app.logistics.routes.purchase_routes import _mensaje_factura

        texto = _mensaje_factura(
            {'puede_aceptar': True, 'tipo': 'factura_proveedor'})
        self.assertIn('verificada', texto)
        self.assertNotIn('se registró', texto,
                         "Aceptada es aceptada: no hay nada que avisar")

    def test_una_foto_ilegible_no_pasa_por_mensaje_de_exito(self):
        # _mensaje_factura solo se usa cuando la foto YA fue aceptada. Si
        # alguien la vuelve a llamar con una foto rechazada, tiene que notarse:
        # un texto de exito en ese caso le diria al usuario que su compra
        # registro cuando no se registro nada.
        from app.logistics.routes import purchase_routes as rutas

        veredicto = {
            'puede_aceptar': False, 'veredicto': 'ilegible', 'tipo': 'desconocido',
        }
        texto_ok = rutas._mensaje_factura(veredicto)
        self.assertNotIn('se registró', texto_ok.lower())
        # El texto que corresponde a una foto rechazada es el de rechazo.
        self.assertIn('no se registró',
                      rutas._mensaje_rechazo_factura(veredicto))


class TestMensajeDeRechazo(unittest.TestCase):
    """
    Modo 'strict': la compra NO se registro, asi que el mensaje tiene que ir en
    futuro y decir QUE rehacer. Reusar _mensaje_factura aqui seria un bug:
    ese dice "la compra se registro, pero..." y no habria ninguna compra.
    """

    def test_rechazo_dice_que_no_se_registro(self):
        from app.logistics.routes.purchase_routes import _mensaje_rechazo_factura

        texto = _mensaje_rechazo_factura(
            {'puede_aceptar': False, 'veredicto': 'dudoso'})
        self.assertIn('no se registró', texto)
        self.assertNotIn('se registró, pero', texto)

    def test_rechazo_ilegible_dice_que_rehaga_la_foto(self):
        from app.logistics.routes.purchase_routes import _mensaje_rechazo_factura

        texto = _mensaje_rechazo_factura(
            {'puede_aceptar': False, 'veredicto': 'ilegible'})
        self.assertIn('Vuelve a tomarla', texto)

    def test_rechazo_no_promete_que_quede_anotado_para_revision(self):
        from app.logistics.routes.purchase_routes import _mensaje_rechazo_factura

        texto = _mensaje_rechazo_factura(
            {'puede_aceptar': False, 'veredicto': 'dudoso'})
        self.assertNotIn('revisión', texto,
                         "No queda nada anotado: la compra no se creo")

    def test_el_rechazo_termina_en_el_texto_limpio(self):
        from app.logistics.routes.purchase_routes import _mensaje_rechazo_preview

        texto = _mensaje_rechazo_preview(
            {'puede_aceptar': False, 'veredicto': 'dudoso', 'puntaje': 5})
        self.assertTrue(texto.endswith(
            'La foto no parece una factura ni un comprobante de compra. Revisa '
            'que hayas fotografiado el comprobante completo, con el emisor, el '
            'RIF y los importes legibles.'), texto)


class TestElClienteTambienFrena(unittest.TestCase):
    """La foto es obligatoria: el navegador no debe dejarla pasar de entrada.

    El servidor es el que manda y siempre vuelve a validar, pero si el cliente
    deja mandar el formulario entero con una foto que ya sabe que esta mala,
    el usuario pierde el trabajo de escribirlo todo para recibir un 400.
    """

    @classmethod
    def setUpClass(cls):
        import os
        cls.ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(cls.ruta, encoding='utf-8') as fh:
            cls.codigo = fh.read()

    def test_no_envia_si_la_revision_fallo(self):
        self.assertIn("estadoFoto === 'error_revision'", self.codigo)
        inicio = self.codigo.index("estadoFoto === 'error_revision'")
        bloque = self.codigo[inicio:inicio + 700]
        self.assertIn('isValid = false', bloque)
        self.assertIn('retryPhotoBtn', self.codigo)
        self.assertIn('90000', self.codigo)

    def test_no_envia_si_la_foto_ya_fue_rechazada(self):
        self.assertIn("estadoFoto === 'rechazada'", self.codigo)
        # Y tiene que invalidar el formulario, no solo avisar.
        inicio = self.codigo.index("estadoFoto === 'rechazada'")
        bloque = self.codigo[inicio:inicio + 700]
        self.assertIn('isValid = false', bloque,
                      "Con la foto rechazada debe frenar el envio")

    def test_no_envia_mientras_la_foto_se_esta_revisando(self):
        self.assertIn("estadoFoto === 'revisando'", self.codigo)
        inicio = self.codigo.index("estadoFoto === 'revisando'")
        bloque = self.codigo[inicio:inicio + 500]
        self.assertIn('isValid = false', bloque)

    def test_el_rechazo_limpia_la_foto_para_poder_reintentarla(self):
        # Si la foto mala se queda en el campo, el usuario no puede corregirla
        # y el formulario queda bloqueado para siempre.
        self.assertIn("input.value = ''", self.codigo)
        self.assertIn("dispatchEvent(new Event('change'))", self.codigo)
        self.assertIn('scrollIntoView', self.codigo)

    def test_la_foto_se_exige_antes_de_armar_la_peticion(self):
        inicio = self.codigo.index("addEventListener('submit'")
        bloque = self.codigo[inicio:inicio + 4000]
        self.assertIn('validateFormBeforeSubmit()', bloque,
                      "El submit debe validar antes de enviar")
        # Y la validacion ocurre antes de construir el FormData.
        self.assertLess(
            bloque.index('validateFormBeforeSubmit()'),
            bloque.index('new FormData()'),
            "Se armaba la peticion antes de validar")


class TestStrictNoDejaPasarElFrontend(unittest.TestCase):
    """El JS descartaba los mensajes del servidor; esto fija el contrato."""

    def test_el_frontend_ya_no_lee_la_clave_que_no_existe(self):
        import os
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()

        self.assertNotIn('result.message', codigo,
                         "El backend responde con 'error', no con 'message'")
        self.assertNotIn('Error de consistencia', codigo,
                         "Se mostraba un texto generico en vez del motivo real")
        self.assertIn('result.error', codigo)

    def test_el_frontend_marca_el_campo_de_la_foto(self):
        import os
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()

        self.assertIn("result.campo === 'invoice_photo'", codigo)

    def test_la_gestion_de_compras_escapa_el_error_del_servidor(self):
        import os
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'purchase_management.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()

        # Los ValueError del backend incluyen el nombre del producto: si se
        # pinta con innerHTML sin escapar, un nombre con HTML se ejecuta.
        self.assertNotIn("+ (data.error || 'Error procesando", codigo,
                         "El error del servidor se insertaba sin escapar (XSS)")
        self.assertIn('escapeHtml(String(d).trim())', codigo)

    def test_el_detalle_no_trata_en_proceso_como_url(self):
        import os
        base = os.path.join(os.path.dirname(__file__), '..', '..',
                            'app', 'templates', 'logistics')
        for nombre in ('purchase_details.html', 'purchase_management.html'):
            with open(os.path.join(base, nombre), encoding='utf-8') as fh:
                plantilla = fh.read()
            self.assertIn("invoice_url.startswith('http')", plantilla,
                          f"{nombre} debe validar que sea una URL real")


class TestConfig(unittest.TestCase):
    def test_hay_tope_global_de_peticion(self):
        app = create_app()
        self.assertGreater(
            app.config['MAX_CONTENT_LENGTH'], 0,
            "Sin MAX_CONTENT_LENGTH un adjunto grande tumba el servidor",
        )

    def test_el_modo_de_validacion_esta_definido(self):
        app = create_app()
        self.assertIn(app.config['INVOICE_VALIDATION_MODE'], ('warn', 'strict'))

    def test_la_config_no_ofrece_por_defecto_un_modo_que_deja_pasar(self):
        # 'warn' ya no deja registrar una compra sin factura, pero el valor por
        # defecto de la configuracion era 'warn'. Debe quedar en 'strict', que
        # es el unico modo coherente con "la foto es obligatoria".
        import os as _os
        ruta = _os.path.join(
            _os.path.dirname(__file__), '..', '..', 'app', 'config.py')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()
        linea = next(
            (l for l in codigo.splitlines()
             if 'INVOICE_VALIDATION_MODE =' in l), '')
        self.assertIn("'strict'", linea,
                      "El modo por defecto debe ser 'strict'")


class TestRevisionAlMontarLaFoto(unittest.TestCase):
    """
    La foto se tiene que revisar en cuanto se monta, no al darle "registrar".

    Antes el unico lugar que miraba la imagen era POST /purchases, y al montar
    un archivo el formulario ya se ponia en verde con un check como si ya
    estuviera aprobado.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        ctx = cls.app.app_context()
        ctx.push()
        from app import db
        db.create_all()
        from app.models import Role, User
        rol = db.session.query(Role).first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        usuario = db.session.query(User).first()
        if not usuario:
            usuario = User(name='Revisor', email='revisor@local',
                           password_hash='x', role_id=rol.id, is_active=True)
            db.session.add(usuario)
            db.session.commit()
        cls.uid = usuario.id
        ctx.pop()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True
        # El OCR real tarda ~25s por foto. Lo que se prueba aqui es el
        # CONTRATO del endpoint (codigos, campo, mensaje, que no registre
        # nada), no el reconocimiento, que ya tiene sus propias pruebas. Se
        # sustituye para que la suite no tarde media hora.
        self._parches = []
        self._fijar_ocr('ilegible', puede_aceptar=False)

    def _fijar_ocr(self, veredicto, puede_aceptar):
        from unittest import mock
        from app.logistics.routes import purchase_routes as rutas

        def leer(archivo_bytes, usar_orientacion=False):
            return (['BANCO DE VENEZUELA', 'COMPROBANTE DE PAGO'], None)

        def evaluar(lineas, umbral=60):
            return {
                'veredicto': veredicto, 'tipo': 'desconocido', 'puntaje': 0,
                'marcas': [], 'puede_aceptar': puede_aceptar,
                'detalle': 'simulado para la prueba',
            }

        self._parches.append(mock.patch.object(rutas, 'leer_texto', leer))
        self._parches.append(mock.patch.object(rutas, 'evaluar_comprobante', evaluar))
        for parche in self._parches[-2:]:
            parche.start()

    def tearDown(self):
        for parche in reversed(self._parches):
            parche.stop()
        self.ctx.pop()

    def _revisar(self, contenido, nombre='foto.jpg'):
        return self.client.post(
            '/logistics/purchases/validar-foto',
            data={'invoice_photo': (io.BytesIO(contenido), nombre)},
            content_type='multipart/form-data',
        )

    def test_el_endpoint_responde_el_veredicto(self):
        respuesta = self._revisar(imagen_bytes())
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertIn('puede_aceptar', datos)
        self.assertIn('veredicto', datos)

    def test_una_foto_que_no_es_comprobante_se_rechaza_al_montarla(self):
        datos = self._revisar(imagen_bytes()).get_json()
        self.assertFalse(datos['puede_aceptar'])

    def test_una_foto_aceptada_avisa_que_sirve(self):
        self._fijar_ocr('aceptado', puede_aceptar=True)
        datos = self._revisar(imagen_bytes()).get_json()
        self.assertTrue(datos['puede_aceptar'])
        self.assertIsNone(datos.get('mensaje'),
                          "Si la foto sirve no hay que avisar de nada")

    def test_no_registra_ninguna_compra(self):
        from app.models import Purchase
        with self.app.app_context():
            antes = db.session.query(Purchase).count()
        self._revisar(imagen_bytes())
        self._revisar(imagen_bytes())
        with self.app.app_context():
            despues = db.session.query(Purchase).count()
        # Revisar la foto es solo lectura: si creara algo, al montar la foto se
        # registrarian compras solas.
        self.assertEqual(despues, antes)

    def test_no_descuenta_stock(self):
        from app.models import Inventory
        with self.app.app_context():
            antes = db.session.query(Inventory).count()
        self._revisar(imagen_bytes())
        with self.app.app_context():
            self.assertEqual(db.session.query(Inventory).count(), antes)

    def test_el_mensaje_no_habla_de_una_compra_no_registrada(self):
        # El mensaje de rechazo del submit dice "la compra no se registro".
        # Aqui el usuario todavia no le dio registrar, asi que ese texto le
        # hablaria de algo que no paso.
        datos = self._revisar(imagen_bytes()).get_json()
        mensaje = (datos.get('mensaje') or '').lower()
        self.assertNotIn('no se registró', mensaje)
        self.assertNotIn('no se registro', mensaje)

    def test_rechaza_un_archivo_que_no_es_imagen(self):
        respuesta = self._revisar(b'esto no es una imagen', 'x.jpg')
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(respuesta.get_json()['puede_aceptar'])

    def test_rechaza_una_peticion_sin_foto(self):
        respuesta = self.client.post(
            '/logistics/purchases/validar-foto', data={},
            content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 400)

    def test_exige_permiso_de_administrador(self):
        from app.models import Role, User
        # Un usuario que NO es admin: revisar la foto es parte del registro, y
        # el registro es solo de administradores.
        rol_comun = db.session.query(Role).filter_by(name='consulta').first()
        if not rol_comun:
            db.session.add(Role(name='consulta'))
            db.session.commit()
        # Otro archivo de pruebas hace drop_all(), asi que el objeto en memoria
        # puede quedar con un id viejo. Se vuelve a leer del servidor.
        rol_id = db.session.query(Role).filter_by(name='consulta').first().id
        usuario = db.session.query(User).filter_by(email='ajeno@local').first()
        if not usuario:
            usuario = User(name='Ajeno', email='ajeno@local', password_hash='x',
                           is_active=True)
            db.session.add(usuario)
        # Se asigna el rol SIEMPRE: si el usuario quedo de una corrida previa,
        # reutilizarlo con el rol que tenia haria que la prueba no probara nada.
        usuario.role_id = rol_id
        db.session.commit()
        otro = self.app.test_client()
        with otro.session_transaction() as sesion:
            sesion['_user_id'] = str(usuario.id)
            sesion['_fresh'] = True
        respuesta = otro.post(
            '/logistics/purchases/validar-foto',
            data={'invoice_photo': (io.BytesIO(imagen_bytes()), 'f.jpg')},
            content_type='multipart/form-data')
        self.assertIn(respuesta.status_code, (302, 403),
                      "Un usuario no administrador no deberia poder usar la revision")

    def test_el_frontend_llama_al_endpoint_al_montar(self):
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()
        self.assertIn("/logistics/purchases/validar-foto", codigo)

    def test_el_verde_solo_se_pinta_si_el_servidor_lo_confirma(self):
        """
        El bug era pintar el dropzone verde con un check al montar CUALQUIER
        archivo, sin mirar nada. El verde solo puede aparecer en el camino que
        primero pasa por la revision.
        """
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()
        inicio = codigo.index("document.getElementById('invoice_photo').addEventListener('change'")
        bloque = codigo[inicio:inicio + 1200]
        self.assertNotIn('text-success', bloque,
                         "El change no debe pintar verde antes de revisar")
        self.assertNotIn('#198754', bloque)

    def test_el_submit_vuelve_a_validar_en_el_servidor(self):
        # Lo que responda el navegador no se toma como cierto: el registro
        # sigue validando la foto en el servidor.
        ruta = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'logistics', 'routes', 'purchase_routes.py')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()
        self.assertIn("validacion_factura = _validar_comprobante_cached(", codigo)


class TestOCRCaidoNoAbreLaPuerta(unittest.TestCase):
    """Si el motor de OCR no esta disponible, NO se puede registrar la compra.

    Este era el bug mas grave de la ronda: cuando leer_texto() fallaba,
    _validar_comprobante() devolvia 'puede_aceptar': True, asi que en modo
    estricto la puerta se abria para CUALQUIER imagen en cuanto el motor
    fallaba, y la compra quedaba guardada sin verificar. Como el comentario
    del codigo decia "para que si el OCR no esta instalado la compra no se
    caiga", el efecto era el contrario de lo que el sistema debia hacer.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        ctx = cls.app.app_context()
        ctx.push()
        db.create_all()
        from app.models import Role, User, Supplier, Product
        rol = db.session.query(Role).filter_by(name='Administrator').first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        # El registro de compras es una operacion de administrador
        # (@require_roles('admin') en la ruta), asi que este usuario necesita
        # ese rol. Con un rol comun la ruta responde 302 y la prueba no estaria
        # midiendo lo que dice medir.
        usuario = db.session.query(User).filter_by(email='caido@local').first()
        if not usuario:
            usuario = User(name='Caido', email='caido@local',
                           password_hash='x', is_active=True)
            db.session.add(usuario)
        usuario.role_id = rol.id
        db.session.commit()
        cls.uid = usuario.id
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-CAIDO').first()
        if not proveedor:
            proveedor = Supplier(name='Proveedor', tax_id='J-CAIDO',
                                 status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='CAIDO1').first()
        if not producto:
            producto = Product(name='Producto', sku='CAIDO1',
                               unit_of_measure='KG', is_active=True)
            db.session.add(producto)
            db.session.commit()
        cls.supplier_id = proveedor.id
        cls.product_id = producto.id
        ctx.pop()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        # El usuario se asegura en cada test, no solo en setUpClass: otras
        # clases de la suite recrean las tablas y el usuario almacenado
        # puede haber desaparecido, con lo que la sesion apuntaria a un id
        # inexistente y la ruta responderia 302 en lugar del codico probado.
        self.uid = self._asegurar_usuario()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True
        from unittest import mock
        from app.logistics.routes import purchase_routes as rutas
        # El motor falla, tal como pasaria si rapidocr u onnxruntime no
        # cargaran. La foto, en cambio, es cualquier cosa: da igual, porque
        # justamente no debe poder aceptarse.
        self._parche = mock.patch.object(
            rutas, 'leer_texto',
            lambda b: ([], 'RapidOCR no esta instalado'))
        self._parche.start()

    def _asegurar_usuario(self):
        from app.models import Role, User
        rol = db.session.query(Role).filter_by(name='Administrator').first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        usuario = db.session.query(User).filter_by(email='caido@local').first()
        if not usuario:
            usuario = User(name='Caido', email='caido@local',
                           password_hash='x', role_id=rol.id, is_active=True)
            db.session.add(usuario)
            db.session.commit()
        else:
            usuario.role_id = rol.id
            db.session.commit()
        return usuario.id

    def tearDown(self):
        self._parche.stop()
        self.ctx.pop()

    def _asegurar_datos(self):
        """Recrea sede, proveedor y producto si otro test borro la base.

        Otras clases de la suite hacen drop_all()/create_all(), asi que lo que
        se creo en setUpClass puede ya no existir cuando corre el test. Sin la
        sede el registro fallaba con un 500 por llave foranea en audit_logs, y
        sin proveedor o producto con otro 500, en vez del 201 que se comprueba
        en modo 'warn'.
        """
        from app.models import Location, Supplier, Product
        sede = db.session.get(Location, 1)
        if not sede:
            sede = Location(id=1, name='Principal', state='VE', is_active=True)
            db.session.add(sede)
            db.session.commit()
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-CAIDO').first()
        if not proveedor:
            proveedor = Supplier(name='Proveedor', tax_id='J-CAIDO',
                                 status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='CAIDO1').first()
        if not producto:
            producto = Product(name='Producto', sku='CAIDO1',
                               unit_of_measure='KG', is_active=True)
            db.session.add(producto)
            db.session.commit()
        self.supplier_id = proveedor.id
        self.product_id = producto.id

    def _registrar(self, contenido):
        self._asegurar_datos()
        return self.client.post('/logistics/purchases', data={
            'supplier_id': str(self.supplier_id),
            'currency': 'USD',
            'exchange_rate': '36,50',
            'user_id': str(self.uid),
            'product_id[]': str(self.product_id),
            'quantity[]': '1',
            'lot_number[]': '',
            'expiration_date[]': '',
            'foreign_price[]': ['100,00'],
            'invoice_photo': (io.BytesIO(contenido), 'foto.jpg'),
        }, content_type='multipart/form-data')

    def test_no_registra_la_compra(self):
        from app.models import Purchase
        antes = db.session.query(Purchase).count()
        respuesta = self._registrar(imagen_bytes())
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(db.session.query(Purchase).count(), antes,
                         "Con el OCR caido se registro una compra sin verificar")

    def test_el_mensaje_no_pide_otra_foto(self):
        # El problema no es la foto: es el motor. Pedir que la vuelva a tomar
        # manda al usuario a repetir algo que no va a funcionar nunca.
        respuesta = self._registrar(imagen_bytes())
        cuerpo = respuesta.get_json() or {}
        # El titular no puede culpar a la foto...
        self.assertIn('sistema', (cuerpo.get('error') or '').lower())
        # ...y la explicacion tiene que decir que el motor esta caido.
        self.assertIn('lector', (cuerpo.get('details') or '').lower())
        # En ningun sitio se le pide que retome la foto.
        completo = str(cuerpo).lower()
        self.assertNotIn('vuelve a tomarla', completo)
        self.assertNotIn('retoma', completo)

    def test_el_modo_warn_tampoco_deja_pasar_la_compra(self):
        # La foto de la factura es obligatoria siempre. Antes el modo 'warn'
        # dejaba registrar la compra con un simple warning al log, y entonces
        # el sistema aceptaba imagenes que no eran facturas. El modo ya no
        # compra evidencia: es solo la referencia de como se evaluo.
        self.app.config['INVOICE_VALIDATION_MODE'] = 'warn'
        try:
            from app.models import Purchase
            antes = db.session.query(Purchase).count()
            respuesta = self._registrar(imagen_bytes())
            self.assertEqual(respuesta.status_code, 400,
                             "En modo 'warn' la compra se registro sin factura")
            self.assertEqual(db.session.query(Purchase).count(), antes)
        finally:
            self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'

    def test_el_preview_no_pinta_verde_una_foto_rechazada(self):
        # El navegador no puede decir que la foto sirve si el OCR la rechazo,
        # aunque el modo no sea strict: si lo hiciera, el usuario se enteraria
        # del problema solo al darle registrar, con todo el formulario lleno.
        self.app.config['INVOICE_VALIDATION_MODE'] = 'warn'
        try:
            respuesta = self.client.post(
                '/logistics/purchases/validar-foto',
                data={'invoice_photo': (io.BytesIO(imagen_bytes()), 'f.jpg')},
                content_type='multipart/form-data')
            datos = respuesta.get_json() or {}
            self.assertFalse(datos['puede_aceptar'])
            self.assertIsNotNone(datos.get('mensaje'))
        finally:
            self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'


class TestErroresDeEntradaNoFiltranInternos(unittest.TestCase):
    """Errores de datos del usuario: mensaje claro, sin traceback ni SQL."""

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        from app.models import Role, User
        rol = db.session.query(Role).first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        # Usuario y rol se reaisan en cada test: otras clases de la suite
        # recrean las tablas y este usuario puede haber desaparecido.
        usuario = db.session.query(User).filter_by(email='errores@local').first()
        if not usuario:
            usuario = User(name='Errores', email='errores@local',
                           password_hash='x', role_id=rol.id, is_active=True)
            db.session.add(usuario)
            db.session.commit()
        else:
            usuario.role_id = rol.id
            db.session.commit()
        self.uid = usuario.id
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True

    def tearDown(self):
        self.ctx.pop()

    def test_las_listas_desalineadas_no_reventan_con_indexerror(self):
        # 2 productos pero 1 sola cantidad. Antes quantities[i] lanzaba
        # IndexError y la respuesta traia str(e), o sea el texto crudo de
        # Python y nada util para el usuario.
        from app.models import Supplier, Product
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-ALIN').first()
        if not proveedor:
            proveedor = Supplier(name='P', tax_id='J-ALIN', status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='ALIN1').first()
        if not producto:
            producto = Product(name='X', sku='ALIN1', unit_of_measure='KG',
                               is_active=True)
            db.session.add(producto)
            db.session.commit()
        respuesta = self.client.post('/logistics/purchases', data={
            'supplier_id': str(proveedor.id),
            'currency': 'USD',
            'exchange_rate': '36,50',
            'user_id': str(self.uid),
            'product_id[]': [str(producto.id), str(producto.id)],
            'quantity[]': ['1'],
            'lot_number[]': [''],
            'expiration_date[]': [''],
            'foreign_price[]': ['100,00'],
            # La foto va porque el endpoint la exige antes de armar las lineas;
            # lo que se prueba aqui es el desalineado de las listas.
            'invoice_photo': (io.BytesIO(imagen_bytes()), 'foto.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 400)
        cuerpo = str(respuesta.get_json()).lower()
        self.assertNotIn('indexerror', cuerpo)
        self.assertNotIn('list index out of range', cuerpo)
        self.assertNotIn('traceback', cuerpo)
        self.assertIn('cantidad', cuerpo)


class TestNumerosConSeparadoresRaros(unittest.TestCase):
    """normalizar_numero: espacios raros y guiones bajos.

    El guion bajo es separador de miles para Decimal() ("1_500" = 1500), y un
    teclado celular pega espacios no separables (U+00A0) o finos (U+2009) al
    copiar un precio. Con replace(' ','') esos ultimos llegaban enteros a
    Decimal() y la compra rebotaba con un error de formato despues de que el
    usuario hubiera llenado todo el formulario.
    """

    def test_espacio_no_separable_se_toma_como_miles(self):
        from app.logistics.requests.purchase_validators import normalizar_numero
        self.assertEqual(normalizar_numero('1 500'), '1500')
        self.assertEqual(normalizar_numero('1 500'), '1500')
        self.assertEqual(normalizar_numero('1 500'), '1500')

    def test_guion_bajo_se_rechaza_con_mensaje(self):
        from app.logistics.requests.purchase_validators import normalizar_numero
        with self.assertRaises(ValueError):
            normalizar_numero('1_500')

    def test_los_formatos_venezolanos_no_cambian(self):
        from app.logistics.requests.purchase_validators import normalizar_numero
        for texto, esperado in (('1.500', '1500'), ('0.500', '0.500'),
                                ('1.234,56', '1234.56'), ('10,335', '10.335'),
                                ('36,50', '36.50')):
            self.assertEqual(normalizar_numero(texto), esperado, texto)


class TestImgBbConTimeout(unittest.TestCase):
    def test_la_subida_pone_timeout(self):
        import os as _os
        ruta = _os.path.join(
            _os.path.dirname(__file__), '..', '..',
            'app', 'integrations', 'imgbb', 'imgbb_services.py')
        with open(ruta, encoding='utf-8') as fh:
            codigo = fh.read()
        # Sin timeout la llamada se queda colgada para siempre si ImgBB no
        # responde, y como corre en un hilo de fondo cada compra sin salida a
        # internet acumulaia un hilo y una conexion abiertas.
        self.assertIn('timeout=', codigo)

    def test_una_respuesta_no_json_no_revienta(self):
        # response.json() sobre un cuerpo vacio o con HTML lanza ValueError, y
        # ese except no era el de requests: el motivo real se perdia.
        from app.integrations.imgbb import imgbb_services
        from unittest import mock

        class RespuestaRota:
            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError('no es json')

        with mock.patch.dict('os.environ', {'IMGBB_API_KEY': 'x'}), \
                mock.patch.object(imgbb_services.requests, 'post',
                                  return_value=RespuestaRota()):
            with self.assertRaises(Exception) as ctx:
                imgbb_services.upload_invoice_image(
                    io.BytesIO(b'x'))
        self.assertIn('ilegible', str(ctx.exception).lower())


def _evaluar(lineas):
    return evaluar_comprobante(limpiar_para_evaluar(lineas))


class TestAuditoriaFalsosPositivos(unittest.TestCase):
    """Ninguna imagen que no sea factura o comprobante puede pasar."""

    CASOS = {
        'cedula_sin_marcadores': [
            'V-18.675.480', 'ANTONIO TORRES MUNOZ', '12/03/1990',
            'VENEZOLANO', 'SOLTERO', 'CARACAS 24/11/2026',
        ],
        'cedula_con_marcadores': [
            'REPUBLICA BOLIVARIANA DE VENEZUELA', 'CEDULA DE IDENTIDAD',
            'V-18.675.480', 'FECHA DE NACIMIENTO 12/03/1990',
        ],
        'carnet_laboral': [
            'EMPRESA C.A.', 'CARNET DEL TRABAJADOR', 'ANTONIO TORRES',
            'CARGO OPERADOR', 'CODIGO 4455',
        ],
        'chat_whatsapp': [
            'Hola, te paso el comprobante manana 24/11/2026 por 150,00 Bs',
            'el total es 150,00 Bs', 'gracias',
        ],
        'menu_restaurante': [
            'PIZZA MARGARITA 15.00', 'REFRESCO 3.00', 'PASTA 12.00',
            'POSTRE 5.00', 'TOTAL 35.00', 'SERVICIO 10%',
        ],
        'menu_con_rif_e_iva': [
            'RESTAURANT EL BUEN SABOR', 'RIF J-31245678-9',
            'PIZZA MARGARITA 15.00', 'REFRESCO 3.00', 'IVA 16% INCLUIDO',
            'TOTAL 18.00',
        ],
        'lista_de_precios': [
            'LISTA DE PRECIOS 2026', 'DISTRIBUIDORA C.A. RIF J-31245678-9',
            'HARINA 50KG 25,00 + IVA 16%', 'TOTAL POR BULTO 29,00',
            'PRECIOS SUJETOS A CAMBIO',
        ],
        'carta_administrativa': [
            'Ciudadano Director, en fecha 24/11/2026 se realizo el pago por un '
            'monto de 150.000,00 Bs, total abonado a la cuenta, atentamente la '
            'administracion del condominio',
        ],
    }

    def test_todos_los_casos_adversos_se_rechazan(self):
        for nombre, lineas in self.CASOS.items():
            with self.subTest(caso=nombre):
                resultado = _evaluar(lineas)
                self.assertFalse(resultado['puede_aceptar'],
                                 f"{nombre} no es un comprobante: {resultado}")
                if nombre in ('cedula_con_marcadores', 'carnet_laboral'):
                    self.assertEqual(resultado['tipo'], 'documento_identidad')
                else:
                    self.assertEqual(resultado['tipo'], 'desconocido')

    def test_una_imagen_blanca_o_negra_no_tiene_texto_que_avale_la_compra(self):
        for lineas in ([], ['']):
            with self.subTest(lineas=lineas):
                resultado = _evaluar(lineas)
                self.assertFalse(resultado['puede_aceptar'])
                self.assertEqual(resultado['veredicto'], 'ilegible')

    def test_un_txt_renombrado_a_jpg_se_rechaza(self):
        texto = b'Nota: esto es un archivo de texto, no una imagen.'
        es_valida, error, _ = PurchaseValidator.validate_invoice_image(
            adjunto(texto, nombre='factura.jpg', content_type='image/jpeg')
        )
        self.assertFalse(es_valida)
        self.assertIn('imagen', _sin_acentos(error))

    def test_subtotal_y_total_sin_numero_de_documento_no_se_aceptan(self):
        lineas = [
            'RIF J-31245678-9', 'SUBTOTAL 100,00', 'MONTO TOTAL 116,00',
            'FECHA 24/11/2026', 'PRECIOS SUJETOS A CAMBIO',
        ]
        resultado = _evaluar(lineas)
        self.assertFalse(resultado['puede_aceptar'],
                         "Sin numero de documento no hay como rastrear la compra")
        self.assertIn('rif', resultado['marcas'])
        self.assertNotIn('numero_documento', resultado['marcas'])


class TestAuditoriaComprobantesReales(unittest.TestCase):
    """Cero falsos negativos con los documentos que si valen."""

    def test_factura_fiscal_completa(self):
        resultado = _evaluar(TEXTO_FACTURA_PROVEEDOR.splitlines())
        self.assertTrue(resultado['puede_aceptar'], resultado)
        self.assertEqual(resultado['tipo'], 'factura_proveedor')

    def test_factura_fiscal_con_rif_en_minusculas(self):
        lineas = [
            'FACTURA', 'PROVEEDOR: COMERCIALIZADORA C.A.',
            'rif: j-31245678-9', 'N DE CONTROL 0045',
            'SUBTOTAL 100,00', 'TOTAL 116,00', 'FECHA 24/11/2026',
        ]
        resultado = _evaluar(lineas)
        self.assertTrue(resultado['puede_aceptar'], resultado)
        self.assertIn('rif', resultado['marcas'])
        self.assertIn('numero_documento', resultado['marcas'])

    def test_comprobante_de_punto_de_venta(self):
        resultado = _evaluar(TEXTO_COMPROBANTE_TARJETA)
        self.assertTrue(resultado['puede_aceptar'], resultado)
        self.assertEqual(resultado['tipo'], 'comprobante_tarjeta')

    def test_nota_de_entrega_comercial(self):
        lineas = [
            'DISTRIBUIDORA LA ESPIGA C.A.', 'RIF: G-20000000-1',
            'NOTA DE ENTREGA NRO 778', 'SUBTOTAL 1.000,00',
            'IMPUESTO 160,00', 'MONTO TOTAL 1.160,00', 'FECHA 24/11/2026',
        ]
        resultado = _evaluar(lineas)
        self.assertTrue(resultado['puede_aceptar'], resultado)
        self.assertEqual(resultado['tipo'], 'factura_proveedor')

    def test_nota_de_venta_con_rif(self):
        lineas = [
            'BODEGON LA ESQUINA', 'RIF V-18675480-4', 'NOTA DE VENTA 0007',
            'SUBTOTAL 50,00', 'IVA 16% 8,00', 'TOTAL 58,00',
        ]
        resultado = _evaluar(lineas)
        self.assertTrue(resultado['puede_aceptar'], resultado)


class TestEntregaSinDuplicados(unittest.TestCase):
    """Timeout del POST e idempotencia del registro de compra."""

    @classmethod
    def setUpClass(cls):
        cls.ruta_js = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'static', 'js', 'logistics', 'register_purchase.js')
        with open(cls.ruta_js, encoding='utf-8') as fh:
            cls.codigo = fh.read()
        cls.ruta_html = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'app', 'templates', 'logistics', 'register_purchase.html')
        with open(cls.ruta_html, encoding='utf-8') as fh:
            cls.html = fh.read()

    def test_el_submit_espera_lo_mismo_que_el_ocr(self):
        self.assertIn('120000', self.codigo)
        self.assertNotIn('submitController.abort(), 30000', self.codigo)

    def test_el_formulario_manda_un_token_de_idempotencia(self):
        self.assertIn("formData.append('submit_token', tokenEnvio)", self.codigo)
        self.assertIn('tokenEnvio = nuevoTokenEnvio()', self.codigo)

    def test_el_html_no_sirve_una_version_vieja_del_js(self):
        self.assertIn("?v=9.17", self.html)

    def test_las_alertas_funcionan_sin_cdn(self):
        self.assertIn('js/vendor/sweetalert2.min.js', self.html)
        self.assertNotIn('cdn.jsdelivr.net/npm/sweetalert2', self.html)
        self.assertTrue(
            os.path.exists(os.path.join(
                os.path.dirname(__file__), '..', '..',
                'app', 'static', 'js', 'vendor', 'sweetalert2.min.js')),
            'El SweetAlert vendorizado tiene que existir para el fallback',
        )

    def test_mostrar_alerta_tiene_respaldo_sin_swal(self):
        inicio = self.codigo.index('function mostrarAlerta(')
        bloque = self.codigo[inicio:inicio + 900]
        self.assertIn("typeof Swal !== 'undefined'", bloque)
        self.assertIn('alertaGlobalCompra', bloque)
        self.assertIn('window.alert(', bloque)

    def test_una_respuesta_vieja_no_pisa_la_foto_nueva(self):
        self.assertIn('controladorRevision.abort()', self.codigo)
        self.assertIn('const token = ++revisionFotoEnCurso;', self.codigo)
        self.assertGreaterEqual(
            self.codigo.count('if (token !== revisionFotoEnCurso) return;'), 2,
            'La respuesta vieja se descarta tanto en exito como en error',
        )

    def test_el_mensaje_no_expone_puntajes_internos(self):
        from app.logistics.routes.purchase_routes import (
            _mensaje_rechazo_factura, _mensaje_rechazo_preview,
        )

        for veredicto in ('dudoso', 'rechazado', 'ilegible', 'sin_lectura'):
            validacion = {'puede_aceptar': False, 'veredicto': veredicto,
                          'puntaje': 5, 'detalle': '5 puntos, tipo desconocido'}
            for texto in (_mensaje_rechazo_preview(validacion),
                          _mensaje_rechazo_factura(validacion)):
                with self.subTest(veredicto=veredicto, texto=texto):
                    self.assertNotIn('puntos', texto.lower())
                    self.assertNotIn('señales', texto.lower())
                    self.assertNotIn('tipo desconocido', texto.lower())

    def test_el_js_no_concatena_el_diagnostico_tecnico(self):
        self.assertNotIn('diagnosticoFoto', self.codigo)
        self.assertNotIn('data.diagnostico', self.codigo)

    def test_ningun_estado_sin_confirmar_deja_enviar_el_formulario(self):
        inicio = self.codigo.index('function validateFormBeforeSubmit(')
        fin = self.codigo.index('function nuevoTokenEnvio(', inicio)
        bloque = self.codigo[inicio:fin]
        for estado in ('rechazada', 'revisando', 'error_revision', 'vacia'):
            with self.subTest(estado=estado):
                marca = f"estadoFoto === '{estado}'"
                self.assertIn(marca, bloque)
                desde = bloque.index(marca)
                cierre = bloque.find('} else if', desde + 1)
                rama = bloque[desde:cierre if cierre != -1 else len(bloque)]
                self.assertIn('isValid = false', rama,
                              f'El estado {estado} no bloquea el envio')
        self.assertIn('if (!validateFormBeforeSubmit()) {', self.codigo)

    def test_el_boton_reintentar_relanza_la_revision(self):
        inicio = self.codigo.index('retryPhotoBtn.addEventListener')
        bloque = self.codigo[inicio:inicio + 400]
        self.assertIn('revisarFoto(input.files[0])', bloque)

    def test_el_timeout_de_la_tasa_habilita_la_entrada_manual(self):
        inicio = self.codigo.index('async function fetchExchangeRate')
        bloque = self.codigo[inicio:inicio + 5000]
        self.assertIn('abortadoPorTiempo', bloque)
        self.assertIn("if (error.name === 'AbortError' && !abortadoPorTiempo)",
                      bloque, 'Un timeout no puede quedarse en silencio')
        self.assertIn("'Ingrese tasa manual'", bloque)

    def test_el_fallo_de_subida_conserva_el_formulario_y_el_token(self):
        inicio = self.codigo.index(
            "if (result.campo === 'invoice_photo' && response.status !== 400) {")
        fin = self.codigo.index('if (response.status >= 500)', inicio)
        bloque = self.codigo[inicio:fin]
        self.assertNotIn('clearDraft()', bloque)
        self.assertNotIn('tokenEnvio = nuevoTokenEnvio()', bloque)
        self.assertIn('setPhotoError(', bloque)


class TestRespaldoDeOrientacion(unittest.TestCase):
    """La pasada rapida va sin clasificacion de angulo; el reintento la activa."""

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.logistics.routes import purchase_routes as rutas
        self.rutas = rutas
        self.lecturas = []
        self._parche = None

    def tearDown(self):
        if self._parche is not None:
            self._parche.stop()
        self.ctx.pop()

    def _montar_lector(self, sin_orientacion, con_orientacion):
        from unittest import mock

        def leer(imagen, usar_orientacion=False):
            self.lecturas.append(usar_orientacion)
            return (con_orientacion if usar_orientacion else sin_orientacion, None)

        self._parche = mock.patch.object(self.rutas, 'leer_texto', leer)
        self._parche.start()

    def test_una_foto_al_reves_se_rescata_con_orientacion(self):
        self._montar_lector(['. .', '..'], TEXTO_FACTURA_PROVEEDOR.splitlines())
        validacion = self.rutas._validar_comprobante(imagen_bytes())
        self.assertEqual(self.lecturas, [False, True])
        self.assertEqual(validacion['veredicto'], 'aceptado')
        self.assertTrue(validacion['puede_aceptar'])

    def test_una_foto_legible_no_paga_el_reintento(self):
        self._montar_lector(TEXTO_FACTURA_PROVEEDOR.splitlines(), ['.'])
        validacion = self.rutas._validar_comprobante(imagen_bytes())
        self.assertEqual(self.lecturas, [False])
        self.assertEqual(validacion['veredicto'], 'aceptado')


class TestFlujoEndToEndCompras(unittest.TestCase):
    """Preview -> cache -> submit, y defensa contra suplantacion."""

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = False
        self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self._asegurar_datos()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True

        from unittest import mock
        from app.logistics.routes import purchase_routes as rutas
        self.llamadas_ocr = 0

        def leer(imagen, usar_orientacion=False):
            self.llamadas_ocr += 1
            if imagen.size == (600, 800):
                return (TEXTO_FACTURA_PROVEEDOR.splitlines(), None)
            return (['Hola, te paso el comprobante manana por 150,00 Bs'], None)

        self._parches = [
            mock.patch.object(rutas, 'leer_texto', leer),
            mock.patch.object(rutas, 'upload_invoice_image',
                              lambda memoria: 'https://i.ibb.co/e2e/factura.jpg'),
        ]
        for parche in self._parches:
            parche.start()
        self.rutas = rutas

    def tearDown(self):
        for parche in reversed(self._parches):
            parche.stop()
        self.ctx.pop()

    def _asegurar_datos(self):
        from app.models import Location, Role, Supplier, Product, User
        sede = db.session.get(Location, 1)
        if not sede:
            db.session.add(Location(id=1, name='Principal', state='VE',
                                    is_active=True))
            db.session.commit()
        rol = db.session.query(Role).filter_by(name='Administrator').first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        usuario = db.session.query(User).filter_by(email='e2e@local').first()
        if not usuario:
            usuario = User(name='E2E', email='e2e@local', password_hash='x',
                           is_active=True)
            db.session.add(usuario)
        usuario.role_id = rol.id
        db.session.commit()
        self.uid = usuario.id
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-E2E').first()
        if not proveedor:
            proveedor = Supplier(name='Proveedor E2E', tax_id='J-E2E',
                                 status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='E2E1').first()
        if not producto:
            producto = Product(name='Producto E2E', sku='E2E1',
                               unit_of_measure='KG', is_active=True)
            db.session.add(producto)
        producto.min_stock = 1
        db.session.commit()
        self.supplier_id = proveedor.id
        self.product_id = producto.id

    def _preview(self, contenido):
        return self.client.post(
            '/logistics/purchases/validar-foto',
            data={'invoice_photo': (io.BytesIO(contenido), 'f.jpg')},
            content_type='multipart/form-data')

    def _registrar(self, contenido, token=''):
        datos = {
            'supplier_id': str(self.supplier_id),
            'currency': 'EUR',
            'exchange_rate': '40,00',
            'user_id': str(self.uid),
            'product_id[]': str(self.product_id),
            'quantity[]': '1',
            'lot_number[]': '',
            'expiration_date[]': '',
            'foreign_price[]': ['100,00'],
            'invoice_photo': (io.BytesIO(contenido), 'f.jpg'),
        }
        if token:
            datos['submit_token'] = token
        return self.client.post('/logistics/purchases', data=datos,
                                content_type='multipart/form-data')

    def _compras(self):
        from app.models import Purchase
        return db.session.query(Purchase).count()

    def test_el_submit_reutiliza_el_veredicto_del_preview(self):
        foto = imagen_bytes(ancho=1200, alto=1600)
        preview = self._preview(foto)
        self.assertTrue(preview.get_json()['puede_aceptar'])
        self.assertEqual(self.llamadas_ocr, 1)

        antes = self._compras()
        respuesta = self._registrar(foto)
        self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
        self.assertEqual(self._compras(), antes + 1)
        self.assertEqual(self.llamadas_ocr, 1,
                         "El submit volvio a correr el OCR de la misma foto")

    def test_una_imagen_distinta_no_hereda_el_veredicto_del_preview(self):
        self._preview(imagen_bytes(ancho=1200, alto=1600))
        antes = self._compras()
        respuesta = self._registrar(imagen_bytes(ancho=1000, alto=1400))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.get_json().get('campo'), 'invoice_photo')
        self.assertEqual(self._compras(), antes,
                         "Se guardo una compra con una foto suplantada")

    def test_el_post_directo_sin_preview_tambien_valida(self):
        antes = self._compras()
        respuesta = self._registrar(imagen_bytes(ancho=900, alto=1300))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self._compras(), antes)

    def test_reenviar_el_mismo_token_no_duplica_la_compra(self):
        import uuid
        token = str(uuid.uuid4())
        foto = imagen_bytes(ancho=1200, alto=1600)
        antes = self._compras()
        primera = self._registrar(foto, token=token)
        self.assertEqual(primera.status_code, 201, primera.get_json())
        segunda = self._registrar(foto, token=token)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primera.get_json()['purchase_id'],
                         segunda.get_json()['purchase_id'])
        self.assertEqual(self._compras(), antes + 1,
                         "El reintento tras un timeout duplico la compra")

    def test_un_token_en_curso_responde_409(self):
        import uuid
        token = f'curso-{uuid.uuid4()}'
        clave = (self.uid, token)
        self.assertTrue(self.rutas._token_reclamar(clave))
        try:
            respuesta = self._registrar(
                imagen_bytes(ancho=1200, alto=1600), token=token)
            self.assertEqual(respuesta.status_code, 409)
        finally:
            self.rutas._token_liberar(clave)


CASOS_QUE_NO_SON_FACTURA = {
    'cedula_venezolana': [
        'REPUBLICA BOLIVARIANA DE VENEZUELA', 'CEDULA DE IDENTIDAD',
        'V-18.675.480', 'FECHA DE NACIMIENTO 12/03/1990', 'VENEZOLANO',
        'SOLTERO', 'CARACAS 24/11/2026',
    ],
    'carnet_laboral': [
        'EMPRESA C.A.', 'CARNET DEL TRABAJADOR', 'ANTONIO TORRES',
        'CARGO OPERADOR', 'CODIGO 4455', 'FECHA DE NACIMIENTO 12/03/1990',
    ],
    'chat_whatsapp': [
        'Hola, te paso el comprobante manana 24/11/2026 por 150,00 Bs',
        'el total es 150,00 Bs', 'gracias',
    ],
    'menu_restaurante': [
        'PIZZA MARGARITA 15.00', 'REFRESCO 3.00', 'PASTA 12.00',
        'TOTAL 30.00', 'IVA 16% 4.80', 'precios sujetos a cambio',
    ],
    'lista_de_precios': [
        'LISTA DE PRECIOS 2026', 'DISTRIBUIDORA C.A. RIF J-31245678-9',
        'HARINA 50KG 25,00 + IVA 16%', 'TOTAL POR BULTO 29,00',
        'PRECIOS SUJETOS A CAMBIO',
    ],
    'imagen_sin_texto': [],
}


class TestNingunaFotoQueNoSeaFacturaPasa(unittest.TestCase):
    """Los dos endpoints rechazan los mismos casos y no dejan compras.

    Las reglas ya estaban probadas como funciones puras; lo que se fija aqui es
    el contrato de las rutas: preview y registro devuelven 400, con mensaje
    limpio, y en la base no queda ninguna compra.
    """

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self._sembrar()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True
        self.lineas = []
        from unittest import mock
        from app.logistics.routes import purchase_routes as rutas
        self._parche = mock.patch.object(rutas, 'leer_texto', self._leer)
        self._parche.start()

    def tearDown(self):
        self._parche.stop()
        self.ctx.pop()

    def _leer(self, imagen, usar_orientacion=False):
        return list(self.lineas), None

    def _sembrar(self):
        from app.models import Location, Product, Role, Supplier, User
        if not db.session.get(Location, 1):
            db.session.add(Location(id=1, name='Principal', state='VE',
                                    is_active=True))
            db.session.commit()
        rol = db.session.query(Role).filter_by(name='Administrator').first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        usuario = db.session.query(User).filter_by(email='matriz@local').first()
        if not usuario:
            usuario = User(name='Matriz', email='matriz@local',
                           password_hash='x', role_id=rol.id, is_active=True)
            db.session.add(usuario)
        usuario.role_id = rol.id
        db.session.commit()
        self.uid = usuario.id
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-MATRIZ').first()
        if not proveedor:
            proveedor = Supplier(name='Proveedor Matriz', tax_id='J-MATRIZ',
                                 status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='MATRIZ1').first()
        if not producto:
            producto = Product(name='Producto Matriz', sku='MATRIZ1',
                               unit_of_measure='KG', is_active=True,
                               min_stock=1)
            db.session.add(producto)
            db.session.commit()
        self.supplier_id = proveedor.id
        self.product_id = producto.id

    def _revisar(self, contenido=None):
        return self.client.post(
            '/logistics/purchases/validar-foto',
            data={'invoice_photo': (io.BytesIO(contenido or imagen_bytes()),
                                    'foto.jpg')},
            content_type='multipart/form-data')

    def _registrar(self, contenido=None, con_foto=True):
        datos = {
            'supplier_id': str(self.supplier_id),
            'currency': 'EUR',
            'exchange_rate': '40,00',
            'user_id': str(self.uid),
            'product_id[]': str(self.product_id),
            'quantity[]': '1',
            'lot_number[]': '',
            'expiration_date[]': '',
            'foreign_price[]': ['100,00'],
        }
        if con_foto:
            datos['invoice_photo'] = (
                io.BytesIO(contenido or imagen_bytes()), 'foto.jpg')
        return self.client.post('/logistics/purchases', data=datos,
                                content_type='multipart/form-data')

    def _compras(self):
        from app.models import Purchase
        return db.session.query(Purchase).count()

    def test_el_preview_rechaza_cada_caso(self):
        for nombre, lineas in CASOS_QUE_NO_SON_FACTURA.items():
            with self.subTest(caso=nombre):
                self.lineas = lineas
                respuesta = self._revisar()
                self.assertIn(respuesta.status_code, (200, 400), nombre)
                datos = respuesta.get_json()
                self.assertFalse(datos['puede_aceptar'], nombre)
                self.assertTrue(datos.get('mensaje'),
                                f'{nombre} se rechazo sin explicarle al usuario')
                plano = _sin_acentos(str(datos))
                self.assertNotIn('puntos', plano)
                self.assertNotIn('senales', plano)

    def test_el_registro_rechaza_cada_caso_sin_crear_compra(self):
        for nombre, lineas in CASOS_QUE_NO_SON_FACTURA.items():
            with self.subTest(caso=nombre):
                self.lineas = lineas
                antes = self._compras()
                respuesta = self._registrar()
                self.assertEqual(respuesta.status_code, 400, nombre)
                datos = respuesta.get_json()
                self.assertEqual(datos.get('campo'), 'invoice_photo', nombre)
                self.assertEqual(self._compras(), antes,
                                 f'{nombre} se guardo como compra')
                plano = _sin_acentos(str(datos))
                self.assertNotIn('puntos', plano)
                self.assertNotIn('senales', plano)

    def test_sin_foto_no_se_crea_la_compra(self):
        antes = self._compras()
        respuesta = self._registrar(con_foto=False)
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.get_json().get('campo'), 'invoice_photo')
        self.assertIn('adjuntar', _sin_acentos(str(respuesta.get_json())))
        self.assertEqual(self._compras(), antes)

    def test_un_txt_renombrado_a_jpg_no_crea_la_compra(self):
        antes = self._compras()
        respuesta = self._registrar(b'Esto es texto plano, no una factura.')
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.get_json().get('campo'), 'invoice_photo')
        self.assertEqual(self._compras(), antes)

    def test_una_foto_truncada_no_crea_la_compra(self):
        antes = self._compras()
        respuesta = self._registrar(imagen_bytes()[:200])
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self._compras(), antes)


COMPROBANTES_VALIDOS = {
    'factura_fiscal': TEXTO_FACTURA_PROVEEDOR.splitlines(),
    'factura_con_rif_en_minusculas': [
        'FACTURA', 'PROVEEDOR: COMERCIALIZADORA C.A.', 'rif: j-31245678-9',
        'N DE CONTROL 0045', 'SUBTOTAL 100,00', 'TOTAL 116,00',
        'FECHA 24/11/2026',
    ],
    'comprobante_de_punto_de_venta': TEXTO_COMPROBANTE_TARJETA,
    'nota_de_entrega': [
        'DISTRIBUIDORA LA ESPIGA C.A.', 'RIF: G-20000000-1',
        'NOTA DE ENTREGA NRO 778', 'SUBTOTAL 1.000,00',
        'IMPUESTO 160,00', 'MONTO TOTAL 1.160,00', 'FECHA 24/11/2026',
    ],
}

URL_FOTO = 'https://i.ibb.co/detalle/factura.jpg'


class TestComprobanteGuardadoSeVeEnElDetalle(unittest.TestCase):
    """Factura valida -> URL guardada -> el detalle la muestra sin el aviso."""

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['INVOICE_VALIDATION_MODE'] = 'strict'
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self._sembrar()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(self.uid)
            sesion['_fresh'] = True
        self.lineas = []
        self.subidas = []
        from unittest import mock
        from app.logistics.routes import purchase_routes as rutas
        self.rutas = rutas
        self._parches = [
            mock.patch.object(rutas, 'leer_texto', self._leer),
            mock.patch.object(rutas, 'upload_invoice_image', self._subir),
            mock.patch.object(rutas, '_ESPERA_REINTENTO_SUBIDA', 0),
        ]
        for parche in self._parches:
            parche.start()

    def tearDown(self):
        for parche in reversed(self._parches):
            parche.stop()
        self.ctx.pop()

    def _leer(self, imagen, usar_orientacion=False):
        return list(self.lineas), None

    def _subir(self, memoria):
        self.subidas.append(memoria.read())
        return URL_FOTO

    def _sembrar(self):
        from app.models import Location, Product, Role, Supplier, User
        if not db.session.get(Location, 1):
            db.session.add(Location(id=1, name='Principal', state='VE',
                                    is_active=True))
            db.session.commit()
        rol = db.session.query(Role).filter_by(name='Administrator').first()
        if not rol:
            rol = Role(name='Administrator')
            db.session.add(rol)
            db.session.commit()
        usuario = db.session.query(User).filter_by(email='detalle@local').first()
        if not usuario:
            usuario = User(name='Detalle', email='detalle@local',
                           password_hash='x', role_id=rol.id, is_active=True)
            db.session.add(usuario)
        usuario.role_id = rol.id
        db.session.commit()
        self.uid = usuario.id
        proveedor = db.session.query(Supplier).filter_by(tax_id='J-DETALLE').first()
        if not proveedor:
            proveedor = Supplier(name='Proveedor Detalle', tax_id='J-DETALLE',
                                 status='ACTIVE')
            db.session.add(proveedor)
            db.session.commit()
        producto = db.session.query(Product).filter_by(sku='DETALLE1').first()
        if not producto:
            producto = Product(name='Producto Detalle', sku='DETALLE1',
                               unit_of_measure='KG', is_active=True,
                               min_stock=1)
            db.session.add(producto)
            db.session.commit()
        self.supplier_id = proveedor.id
        self.product_id = producto.id

    def _registrar(self):
        return self.client.post('/logistics/purchases', data={
            'supplier_id': str(self.supplier_id),
            'currency': 'EUR',
            'exchange_rate': '40,00',
            'user_id': str(self.uid),
            'product_id[]': str(self.product_id),
            'quantity[]': '1',
            'lot_number[]': '',
            'expiration_date[]': '',
            'foreign_price[]': ['100,00'],
            'invoice_photo': (io.BytesIO(imagen_bytes()), 'factura.jpg'),
        }, content_type='multipart/form-data')

    def _esperar_url(self, purchase_id, limite=10.0):
        from app.models import Purchase
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            db.session.expire_all()
            compra = db.session.get(Purchase, purchase_id)
            if compra and compra.invoice_url == URL_FOTO:
                return compra
            time.sleep(0.05)
        raise AssertionError(
            f'La compra {purchase_id} quedo en '
            f'{getattr(compra, "invoice_url", None)!r} y no en la URL subida')

    def test_cada_comprobante_valido_se_guarda_y_se_ve_en_el_detalle(self):
        for nombre, lineas in COMPROBANTES_VALIDOS.items():
            with self.subTest(comprobante=nombre):
                self.lineas = lineas
                respuesta = self._registrar()
                self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
                self.assertTrue(respuesta.get_json()['factura']['aceptada'])

                compra = self._esperar_url(respuesta.get_json()['purchase_id'])
                self.assertEqual(compra.invoice_url, URL_FOTO)

                detalle = self.client.get(f'/logistics/purchases/{compra.id}')
                self.assertEqual(detalle.status_code, 200)
                html = detalle.get_data(as_text=True)
                self.assertNotIn('no se pudo guardar', html,
                                 f'{nombre}: el detalle avisa un fallo que no hubo')
                self.assertIn(URL_FOTO, html)
                self.assertIn('Ver Evidencia', html)

    def test_la_subida_recibe_los_bytes_completos_de_la_factura(self):
        self.lineas = COMPROBANTES_VALIDOS['factura_fiscal']
        foto = imagen_bytes()
        respuesta = self.client.post('/logistics/purchases', data={
            'supplier_id': str(self.supplier_id),
            'currency': 'EUR',
            'exchange_rate': '40,00',
            'user_id': str(self.uid),
            'product_id[]': str(self.product_id),
            'quantity[]': '1',
            'lot_number[]': '',
            'expiration_date[]': '',
            'foreign_price[]': ['100,00'],
            'invoice_photo': (io.BytesIO(foto), 'factura.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
        self._esperar_url(respuesta.get_json()['purchase_id'])
        self.assertEqual(len(self.subidas), 1)
        self.assertGreater(len(self.subidas[0]), 0)
        self.assertEqual(self.subidas[0], foto)

    def test_el_detalle_anulado_sin_fecha_de_auditoria_no_rompe(self):
        from sqlalchemy import text
        from app.models import Purchase, PurchaseAuditLog

        self.lineas = COMPROBANTES_VALIDOS['factura_fiscal']
        respuesta = self._registrar()
        self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
        pid = respuesta.get_json()['purchase_id']
        compra = db.session.get(Purchase, pid)
        compra.status = 'ANNULLED'
        log = PurchaseAuditLog(
            purchase_id=pid, action_type='ANNULLED', previous_data={},
            new_data={}, user_id=self.uid)
        db.session.add(log)
        db.session.commit()
        db.session.execute(
            text('UPDATE purchase_audit_log SET timestamp = NULL WHERE id = :id'),
            {'id': log.id})
        db.session.commit()

        detalle = self.client.get(f'/logistics/purchases/{pid}')
        self.assertEqual(detalle.status_code, 200)

    def test_el_detalle_avisa_cuando_la_foto_no_se_guardo(self):
        from app.models import Purchase
        self.lineas = COMPROBANTES_VALIDOS['factura_fiscal']
        respuesta = self._registrar()
        self.assertEqual(respuesta.status_code, 201, respuesta.get_json())
        compra = self._esperar_url(respuesta.get_json()['purchase_id'])

        for marca in (self.rutas._MARCA_FALLO_SUBIDA, 'En proceso...'):
            with self.subTest(marca=marca):
                compra.invoice_url = marca
                db.session.commit()
                detalle = self.client.get(f'/logistics/purchases/{compra.id}')
                self.assertEqual(detalle.status_code, 200)
                html = detalle.get_data(as_text=True)
                self.assertIn('no se pudo guardar', html)
                self.assertNotIn('Ver Evidencia', html)
        db.session.rollback()


if __name__ == '__main__':
    unittest.main(verbosity=2)
