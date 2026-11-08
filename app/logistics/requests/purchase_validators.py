from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import re

from PIL import Image, UnidentifiedImageError


# --- Factura: que la foto sea realmente una foto ---------------------------
# El atributo accept="image/*" del <input> es una pista visual para el usuario,
# no una proteccion: se quita quitando el atributo. Aqui se comprueba el archivo
# de verdad, que es lo unico que el servidor puede verificar.
MAX_IMAGEN_BYTES = 8 * 1024 * 1024
MIN_LADO_IMAGEN = 320
MAX_LADO_IMAGEN = 12000
FORMATOS_PERMITIDOS = {'JPEG', 'PNG', 'WEBP'}

# La extension por si se quiere conservar la original al renombrar.
EXTENSION_POR_FORMATO = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}

# Marcador de fin de imagen JPEG (EOI). Si no esta, el archivo esta cortado.
MARCADOR_FIN_JPEG = b'\xff\xd9'
MARCADOR_FIN_PNG = b'IEND'


def _decodifica_completa(contenido, formato):
    """
    Fuerza la decodificacion completa y revisa el marcador de fin.

    Image.verify() alcanza con la cabecera, asi que un JPEG al que le falta la
    mitad de abajo lo aprueba. Decodificar de verdad si lo detecta, y el
    marcador de cierre avisa de una subida interrumpida aunque los ultimos
    pixeles si decodifiquen.
    """
    try:
        with Image.open(io.BytesIO(contenido)) as imagen:
            imagen.load()
    except Exception:
        return False

    if formato == 'JPEG' and MARCADOR_FIN_JPEG not in contenido[-64:]:
        return False
    if formato == 'PNG' and MARCADOR_FIN_PNG not in contenido[-32:]:
        return False
    return True


# --- Factura: reconocer el tipo de comprobante ----------------------------
# Se aceptan dos clases de documento, porque en una pizzeria las dos son
# legitimas y en la practica es lo unico que se tiene a mano:
#   1. Factura de proveedor (formal, con N de factura y N de control).
#   2. Comprobante de tarjeta (el papel del punto de venta al pagar con
#      debito o credito), que no tiene impuestos ni numero de control.
#
# Los marcadores se tomaron de una foto real de un comprobante de tarjeta
# Los marcadores se tomaron de una foto real de un comprobante de tarjeta de
# debito, leida con RapidOCR, y de los impresos fiscales Venezuela.
#
# Ninguna regla de este bloque necesita OCR: son funciones puras sobre texto,
# asi que se pueden probar sin levantar la aplicacion.

# El RIF venezolano real es letra + 8 digitos + 1 digito verificador, o sea
# hasta 9 digitos. El patron que se habia considerado antes
# ([JVEG]-[0-9]{8}-[0-9], con guion obligatorio antes del ultimo digito) NO
# reconocia el RIF de la foto de prueba (V-186754804, que no lleva ese guion).
PATRON_RIF = re.compile(r'(?<![A-Za-z0-9])[JVEG][\s.\-]{0,2}\d{7,9}(?!\d)')
PATRON_TARJETA_ENMASCARADA = re.compile(r'\d{4,6}\s?\*{2,}\s?\d{2,4}')
PATRON_MONTOS = re.compile(r'\b\d{1,3}(?:[.\s]\d{3})+(?:[.,]\d{2})?\b|\b\d+[.,]\d{2}\b')
PATRON_FECHA = re.compile(
    r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b'   # 27/09/2026
    r'|\b\d{4}[/\-]\d{1,2}[/\-]\d{1,2}\b'    # 2026/09/27
    r'|\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\b'  # 27 de septiembre de 2026
)

# Comprobante de tarjeta / pago con POS.
MARCAS_TARJETA = {
    'recibo_compra': ('recibo de compra', 'recibo de compra', 'nota de consumo'),
    'banco': ('banco de venezuela', 'ban mercantil', 'banesco', 'bancamiga',
              'banco union', 'bancamiga', 'provinciabank', 'bancrecer'),
    'tarjeta': ('master debito', 'mastercard', 'master credito', 'debito',
                'credito', 'tarjeta', 'visa', 'american express'),
    'terminal': ('terminal', 'term:', 'term ', 'afiliad', 'afil:'),
    'lote_trace': ('lote no', 'lote n', 'lote:', 'trace', 'traza', 'aprob:',
                   'autorizad', 'aprobada', 'aprobado'),
    'aid_ref': ('aid:', ' aid', 'ref:', 'referencia:'),
    'obligacion': ('me obligo a pagar', 'nota de consumo', 'banco emisor'),
    'sin_firma': ('no requiere firma', 'no reuqiere firma', 'firma del cliente'),
}

# Factura formal de proveedor.
MARCAS_FACTURA = {
    'factura': ('factura', 'n de factura', 'nro factura', 'nota de venta',
                'nota de debito', 'comprobante de venta'),
    'control': ('n de control', 'nro de control', 'n control', 'numero de control',
                'control:', 'orden de compra'),
    'subtotal_iva': ('subtotal', 'sub total', 'sub-total', 'iva', 'igtf',
                     'base imponible', 'impuesto', 'alicuota'),
    'total': ('total', 'importe total', 'monto total', 'gran total'),
    'proveedor': ('proveedor', 'razon social', 'nombre o razon social', 'emisor'),
    'moneda_fiscal': ('bolivares', 'bs.', 'bs ', 'usd', 'dolares', 'moneda'),
}

# Sin esto no hay nada que decidir: una foto de producto no llega ni a 15.
MIN_CARACTERES_UTIL = 60
MIN_CARACTERES_ACEPTABLE = 25

TIPO_FACTURA = 'factura_proveedor'
TIPO_TARJETA = 'comprobante_tarjeta'
TIPO_DESCONOCIDO = 'desconocido'

VEREDICTO_ACEPTADO = 'aceptado'
VEREDICTO_DUDOSO = 'dudoso'
VEREDICTO_ILEGIBLE = 'ilegible'
VEREDICTO_RECHAZADO = 'rechazado'


def _cuantas_marcas_encuentra(texto, marcas):
    return [nombre for nombre, needles in marcas.items()
            if any(needle in texto for needle in needles)]


def evaluar_comprobante(texto, umbral=60):
    """
    Decide que tipo de comprobante es el texto leido de la foto.

    No lanza y no depende del OCR: recibe texto y devuelve un dict. Asi se
    puede probar con las 40 fotos y con casos inventados sin instalar nada.

    Devuelve dict con:
        veredicto   : aceptado | dudoso | ilegible | rechazado
        tipo        : factura_proveedor | comprobante_tarjeta | desconocido
        puntaje     : 0-100
        marcas      : que señales se encontraron
        puede_aceptar: True si se supero el umbral
    """
    texto = (texto or '').lower()
    largo = len(texto)

    if largo < MIN_CARACTERES_ACEPTABLE:
        return {
            'veredicto': VEREDICTO_ILEGIBLE,
            'tipo': TIPO_DESCONOCIDO,
            'puntaje': 0,
            'marcas': [],
            'puede_aceptar': False,
            'detalle': (
                f'Solo se leyeron {largo} caracteres. La foto esta borrosa, '
                'muy lejos o con poca luz: no se puede leer.'
            ),
        }

    marcas_factura = _cuantas_marcas_encuentra(texto, MARCAS_FACTURA)
    marcas_tarjeta = _cuantas_marcas_encuentra(texto, MARCAS_TARJETA)

    tiene_rif = bool(PATRON_RIF.search(texto))
    tiene_tarjeta = bool(PATRON_TARJETA_ENMASCARADA.search(texto))
    tiene_montos = bool(PATRON_MONTOS.search(texto))
    tiene_fecha = bool(PATRON_FECHA.search(texto))

    puntaje = 0
    marcas = []

    # Se elige el tipo con mas señales. La foto real de prueba tiene 5 marcas
    # de tarjeta y 0 de factura, asi que el orden importa: un comprobante de
    # tarjeta dice "recibo de compra", no "factura".
    if len(marcas_tarjeta) > len(marcas_factura) and marcas_tarjeta:
        tipo = TIPO_TARJETA
        puntaje += 35 + 7 * len(marcas_tarjeta)
        marcas += [f'tarjeta:{m}' for m in marcas_tarjeta]
    elif marcas_factura:
        tipo = TIPO_FACTURA
        puntaje += 35 + 7 * len(marcas_factura)
        marcas += [f'factura:{m}' for m in marcas_factura]
    else:
        tipo = TIPO_DESCONOCIDO

    if tiene_rif:
        puntaje += 15
        marcas.append('rif')
    if tiene_tarjeta and tipo == TIPO_TARJETA:
        puntaje += 12
        marcas.append('tarjeta_enmascarada')
    if tiene_montos:
        puntaje += 10
        marcas.append('montos')
    if tiene_fecha:
        puntaje += 8
        marcas.append('fecha')
    if largo >= MIN_CARACTERES_UTIL:
        puntaje += 5
        marcas.append('texto_suficiente')

    # Un documento legible pero sin ninguna señal conocida no es una factura.
    if tipo == TIPO_DESCONOCIDO:
        puntaje = min(puntaje, 20)

    puntaje = min(puntaje, 100)

    if puntaje >= umbral:
        veredicto = VEREDICTO_ACEPTADO
    elif largo < MIN_CARACTERES_UTIL:
        veredicto = VEREDICTO_ILEGIBLE
    else:
        veredicto = VEREDICTO_DUDOSO

    return {
        'veredicto': veredicto,
        'tipo': tipo,
        'puntaje': puntaje,
        'marcas': marcas,
        'puede_aceptar': veredicto == VEREDICTO_ACEPTADO,
        'detalle': f"{puntaje} puntos, tipo {tipo}, {len(marcas)} señales.",
    }


def normalizar_numero(valor):
    """Normaliza formatos de miles (2.000.000) y coma decimal (2,50) a punto.

    Aplica la convencion venezolana UNA sola vez, sobre el texto que el usuario
    escribio: el punto separa miles y la coma separa decimales.

    El formulario debe enviar el texto crudo del campo, no un numero ya
    parseado por el navegador. Si el JS reformatara antes, "10,335" (diez con
    trescientos treinta y cinco) llegaria como "10.335" y este punto se
    tomaria por separador de miles, dejando 10335: un error de 1000x
    silencioso en precios, cantidades y tasa.
    """
    # \s y no unreplace(' ',''): en un celular el teclado pega espacios no
    # separables (U+00A0) o finos (U+2009) al copiar un precio. Con el
    # replace de espacio normal esos caracteres llegaban enteros a Decimal() y
    # la compra rebotaba con un error de formato DESPUES de que el usuario
    # hubiera llenado todo el formulario.
    s = re.sub(r'\s+', '', str(valor or ''))

    if not s:
        return s

    # Decimal() acepta separadores de miles con guion bajo ("1_500" = 1500),
    # y tambien formas que no son numeros. Se rechazan aqui para que el error
    # sea un mensaje de validacion y no un InvalidOperation del servidor.
    if '_' in s:
        raise ValueError(
            f"'{valor}' no es un número válido: no se usan guiones bajos "
            f"como separador de miles."
        )

    if ',' in s:
        return s.replace('.', '').replace(',', '.')

    # Un punto tras un "0" inicial no puede ser separador de miles: nadie
    # escribe 0.500 para querer 500, lo escribe para 0,5. Antes "0.500" se
    # convertía en 500 (error de 1000x) y "0.050" en 50.
    if re.match(r'^0+\.\d+$', s):
        return s

    return re.sub(r'\.(?=\d{3}(?!\d))', '', s)


# Codigos que el sistema reconoce como bolívares. El canonico es 'BS'.
MONEDAS_BS = ('BS', 'VES', 'BSS', 'BS.', 'BS,S', 'BOLIVAR', 'BOLIVARES')
MONEDAS_EXTRANJERAS = ('USD', 'EUR')


def normalizar_moneda(valor):
    """Devuelve el codigo de moneda canonico: 'BS' para bolívares, si no en mayusculas.

    Unifica el criterio que antes estaba duplicado en el repositorio, el servicio
    de gestion y el de registro, donde 'BS.', 'BSS' y 'VES' se comparaban contra
    tuplas distintas.
    """
    s = str(valor or '').strip().upper()
    if s in MONEDAS_BS:
        return 'BS'
    return s


def es_moneda_bs(valor):
    """True si la moneda es bolívares (el monto ya está en Bs y no se multiplica
    por la tasa)."""
    return normalizar_moneda(valor) == 'BS'


def parsear_fecha(valor):
    """Parsea una fecha AAAA-MM-DD. Devuelve None si viene vacía.

    Lanza ValueError con un mensaje legible si el formato es invalido, para no
    filtrar el error interno de strptime al usuario.
    """
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f"La fecha '{s}' no tiene el formato AAAA-MM-DD.")


def parsear_decimal(valor, campo, minimo=None, maximo=None):
    """Convierte a Decimal tolerando formato es-VE. Lanza ValueError con mensaje claro."""
    try:
        d = Decimal(normalizar_numero(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"El valor de '{campo}' no es numérico: {valor!r}")
    if minimo is not None and d < minimo:
        raise ValueError(f"'{campo}' debe ser mayor o igual a {minimo}.")
    if maximo is not None and d > maximo:
        raise ValueError(f"'{campo}' excede el máximo permitido ({maximo}).")
    return d


class PurchaseValidator:
    @staticmethod
    def validate_header(data):
        errors = {}
        
        if not data.get('supplier_id'):
            errors['supplier_id'] = "Debes seleccionar un proveedor válido."
        else:
            try:
                supplier_id = int(data['supplier_id'])
                if supplier_id <= 0:
                    errors['supplier_id'] = "Identificador de proveedor inválido."
            except (ValueError, TypeError):
                errors['supplier_id'] = "El proveedor debe ser un identificador numérico."

        currency = normalizar_moneda(data.get('currency'))
        if currency not in ('USD', 'EUR', 'BS'):
            errors['currency'] = "La moneda debe ser obligatoriamente USD, EUR o BS."

        exchange_rate_raw = data.get('exchange_rate')
        if exchange_rate_raw is None or str(exchange_rate_raw).strip() == '':
            errors['exchange_rate'] = "La tasa de cambio es obligatoria."
        else:
            try:
                rate = Decimal(normalizar_numero(exchange_rate_raw))
                if rate <= Decimal('0.00'):
                    errors['exchange_rate'] = "La tasa de cambio debe ser un número mayor a cero."
                elif rate > Decimal('999999.99'):
                    errors['exchange_rate'] = "La tasa de cambio excede el límite permitido."
            except (InvalidOperation, TypeError, ValueError):
                errors['exchange_rate'] = "La tasa de cambio debe ser un valor numérico válido."

        if not data.get('user_id'):
            errors['user_id'] = "El usuario comprador es obligatorio."

        return errors

    @staticmethod
    def validate_items(items):
        errors = {}
        
        if not isinstance(items, list) or len(items) == 0:
            return {"items": "Debe incluir al menos un producto en la tabla de compras."}
            
        for index, item in enumerate(items):
            prod_id_raw = item.get('product_id')
            if not prod_id_raw:
                errors[f'item_{index}_product_id'] = "Debes seleccionar un producto válido."
            else:
                try:
                    if int(prod_id_raw) <= 0:
                        errors[f'item_{index}_product_id'] = "Identificador de producto inválido."
                except (ValueError, TypeError):
                    errors[f'item_{index}_product_id'] = "El producto debe ser un número entero."

            qty_raw = item.get('quantity')
            try:
                qty = Decimal(normalizar_numero(qty_raw))
                if qty < Decimal('0.01'):
                    errors[f'item_{index}_quantity'] = "La cantidad mínima es 0.01."
                elif qty > Decimal('999999.99'):
                    errors[f'item_{index}_quantity'] = "La cantidad excede el límite permitido (máx 999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_quantity'] = "Cantidad numérica inválida."

            price_raw = item.get('foreign_price')
            try:
                price = Decimal(normalizar_numero(price_raw))
                if price < Decimal('0.01'):
                    errors[f'item_{index}_foreign_price'] = "El precio unitario mínimo es 0.01."
                elif price > Decimal('9999999.99'):
                    errors[f'item_{index}_foreign_price'] = "El precio unitario excede el límite permitido (máx 9,999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_foreign_price'] = "Precio unitario numérico inválido."
                
        return errors

    @staticmethod
    def validate_edit_items(items):
        errors = {}

        if not isinstance(items, list) or len(items) == 0:
            return {"items": "Debe enviar al menos un insumo para la edición."}

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                # Antes se hacía item.get(...) directo y un string o un null en
                # la lista provocaba AttributeError -> 500 en toda la ruta.
                errors[f'item_{index}'] = "Cada insumo debe ser un objeto válido."
                continue
            item_id = item.get('id')
            if not item_id:
                errors[f'item_{index}_id'] = "Identificador de insumo faltante."

            if str(item_id).startswith('new_'):
                prod_id_raw = item.get('product_id')
                if not prod_id_raw:
                    errors[f'item_{index}_product_id'] = "Debes seleccionar un producto para el nuevo insumo."
                else:
                    try:
                        if int(prod_id_raw) <= 0:
                            errors[f'item_{index}_product_id'] = "Identificador de producto inválido."
                    except (ValueError, TypeError):
                        errors[f'item_{index}_product_id'] = "El producto debe ser un número entero."

            qty_raw = item.get('quantity')
            try:
                qty = Decimal(normalizar_numero(qty_raw))
                if qty < Decimal('0.01'):
                    errors[f'item_{index}_quantity'] = "La cantidad mínima es 0.01."
                elif qty > Decimal('999999.99'):
                    errors[f'item_{index}_quantity'] = "La cantidad excede el límite permitido (máx 999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_quantity'] = "Cantidad numérica inválida."

            price_raw = item.get('foreign_price')
            try:
                price = Decimal(normalizar_numero(price_raw))
                if price < Decimal('0.01'):
                    errors[f'item_{index}_foreign_price'] = "El precio unitario mínimo es 0.01."
                elif price > Decimal('9999999.99'):
                    errors[f'item_{index}_foreign_price'] = "El precio unitario excede el límite permitido (máx 9,999,999.99)."
            except (InvalidOperation, TypeError, ValueError):
                errors[f'item_{index}_foreign_price'] = "Precio unitario numérico inválido."

            # La fecha de vencimiento se usaba directo con strptime y su error
            # interno se mostraba al usuario; se valida aqui con mensaje claro.
            if item.get('expiration_date'):
                try:
                    parsear_fecha(item['expiration_date'])
                except ValueError as fe:
                    errors[f'item_{index}_expiration_date'] = str(fe)

            # lot_number se trunca a 50 chars en BD (String(50)).
            if item.get('lot_number') and len(str(item['lot_number']).strip()) > 50:
                errors[f'item_{index}_lot_number'] = "El número de lote no puede superar 50 caracteres."

            if 'id' in item and not str(item['id']).startswith('new_'):
                try:
                    if int(item['id']) <= 0:
                        errors[f'item_{index}_id'] = "Identificador de insumo inválido."
                except (ValueError, TypeError):
                    errors[f'item_{index}_id'] = "El identificador de insumo debe ser un entero."

        return errors

    @staticmethod
    def validate_edit_reason(reason):
        """Valida el motivo de la edición. Devuelve un mensaje de error o None."""
        if not isinstance(reason, str):
            return "El motivo debe ser un texto."
        if len(reason.strip()) < 5:
            return "Debe proporcionar un motivo válido para justificar la edición."
        if len(reason) > 500:
            return "El motivo no puede superar 500 caracteres."
        return None

    @classmethod
    def validate_invoice_image(cls, archivo):
        """
        Comprueba que el archivo adjunto sea una imagen usable.

        Antes solo se miraba que el campo viniera informado, y despues se hacia
        archivo.read() sin limite: cualquier admin podia mandar un .exe de 2 GB
        (que se iba entero a la memoria) o cualquier archivo disfrazado de .jpg.

        Devuelve (es_valida, mensaje_error, info) donde info trae el formato y
        los bytes reales, ya leidos, para no tener que volver a leer el stream.
        """
        if not archivo or not archivo.filename:
            return False, "Debe adjuntar la foto de la factura.", None

        # 1. Tamano, medido sobre el archivo y no solo por el content-type.
        #    Se posiciona al final porque Werkzeug entrega el cursor al inicio.
        try:
            archivo.stream.seek(0, io.SEEK_END)
            total_bytes = archivo.stream.tell()
            archivo.stream.seek(0)
        except (AttributeError, OSError, ValueError):
            return False, "No se pudo leer el archivo adjunto.", None

        if total_bytes == 0:
            return False, "La foto de la factura está vacía.", None

        if total_bytes > MAX_IMAGEN_BYTES:
            return False, (
                f"La foto no puede superar {MAX_IMAGEN_BYTES // (1024 * 1024)} MB "
                f"(recibida: {total_bytes / (1024 * 1024):.1f} MB)."
            ), None

        # 2. Que el contenido sea una imagen de verdad. Pillow lee la cabecera
        #    y dice el formato real, no el que afirme la extension.
        contenido = archivo.stream.read()
        try:
            with Image.open(io.BytesIO(contenido)) as imagen:
                formato = (imagen.format or '').upper()
                ancho, alto = imagen.size
                imagen.verify()  # revisa que el archivo no este truncado
        except UnidentifiedImageError:
            return False, (
                "El archivo adjunto no es una imagen. Solo se aceptan fotos "
                "o capturas en JPG, PNG o WEBP."
            ), None
        except (OSError, ValueError, Image.DecompressionBombError):
            return False, "La imagen está dañada o incompleta. Vuelve a tomarla.", None

        # 3. Dimensiones ANTES de decodificar. El tamaño sale de la cabecera,
        #    asi que no cuesta nada leerlo, y rechazarlo aqui evita que
        #    _decodifica_completa() expanda los pixeles de una "bomba de
        #    descompresion" (imagenes de 8 MB que al descomprimirse ocupan
        #    cientos de MB en memoria). Antes el limite de MAX_LADO_IMAGEN se
        #    comprobaba DESPUES de decodificar, o sea que la memoria se
        #    consumia antes de poder rechazar la imagen.
        if min(ancho, alto) < MIN_LADO_IMAGEN:
            return False, (
                f"La foto es muy pequeña ({ancho}x{alto}). "
                f"Se necesita al menos {MIN_LADO_IMAGEN}x{MIN_LADO_IMAGEN} para poder leerla."
            ), None

        if max(ancho, alto) > MAX_LADO_IMAGEN:
            return False, (
                f"La imagen es demasiado grande ({ancho}x{alto}). "
                f"El máximo por lado es {MAX_LADO_IMAGEN} píxeles."
            ), None

        # verify() es tolerante: un JPEG cortado a la mitad lo aprueba. Se
        # fuerza ademas la decodificacion completa y se comprueba el marcador
        # de fin de imagen, que es lo que delata una subida interrumpida.
        if not _decodifica_completa(contenido, formato):
            return False, (
                "La imagen está incompleta o dañada. "
                "Vuelve a subirla para que no se corte la descarga."
            ), None

        if formato not in FORMATOS_PERMITIDOS:
            return False, (
                f"El formato {formato or 'desconocido'} no se admite. "
                f"Usa JPG, PNG o WEBP."
            ), None

        info = {

            'formato': formato,
            'extension': EXTENSION_POR_FORMATO.get(formato, '.jpg'),
            'bytes': contenido,
            'total_bytes': total_bytes,
            'ancho': ancho,
            'alto': alto,
        }
        return True, None, info

    @classmethod
    def validate_create(cls, data):
        if not data or not isinstance(data, dict):
            return False, {"error": "No se proporcionaron datos para procesar la compra."}

        header_errors = cls.validate_header(data)
        item_errors = cls.validate_items(data.get('items', []))
        
        all_errors = {**header_errors, **item_errors}
        return len(all_errors) == 0, all_errors