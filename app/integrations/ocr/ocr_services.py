"""
Lectura de texto de la foto de la factura, en local y sin internet.

Usa RapidOCR (Apache-2.0), que es motor de ONNX: no necesita PyTorch ni
PyGoogle. El modelo se descarga una sola vez al instalar y queda en
.venv/lib/.../rapidocr/models, asi que despues funciona sin conexion.

Se expone solo texto. La decision de si esa foto es una factura no se toma
aqui, sino en PurchaseValidator, que son reglas puras y testeables.
"""
import io
import logging
import re
import threading
import time
import unicodedata

from PIL import Image, ImageOps

MAX_LADO_OCR = 800

_PARAMS_MOTOR = {
    'EngineConfig.onnxruntime.intra_op_num_threads': 2,
    'EngineConfig.onnxruntime.inter_op_num_threads': 1,
    'Det.limit_type': 'max',
    'Det.limit_side_len': MAX_LADO_OCR,
}

_motores = {}
_candado = threading.Lock()
_semaforo_ocr = threading.Semaphore(1)
_log = logging.getLogger('app')

# RapidOCR escribe un INFO por cada modelo que carga. En un servidor con
# peticiones concurrentes eso llena el log de ruido.
logging.getLogger('rapidocr').setLevel(logging.ERROR)


class OCRNoDisponible(RuntimeError):
    """El motor de OCR no se pudo cargar. El flujo debe continuar sin el."""


def _construir_motor(usar_orientacion=False):
    try:
        from rapidocr import RapidOCR
    except ImportError as error:
        raise OCRNoDisponible(
            "RapidOCR no esta instalado. Instale con 'pip install rapidocr onnxruntime'."
        ) from error

    params = dict(_PARAMS_MOTOR)
    params['Global.use_cls'] = bool(usar_orientacion)

    try:
        return RapidOCR(params=params)
    except ImportError as error:
        # rapidocr no declara onnxruntime como dependencia: es un extra, y sin
        # el la inicializacion falla con un ImportError poco descriptivo.
        raise OCRNoDisponible(
            "Falta onnxruntime, que rapidocr no instala solo. "
            "Instalelo con 'pip install onnxruntime'."
        ) from error
    except Exception as error:
        raise OCRNoDisponible(f"No se pudo iniciar el motor de OCR: {error}") from error


def obtener_motor(usar_orientacion=False):
    """
    Devuelve el motor ya inicializado, creandolo en la primera llamada.

    Cargar los modelos cuesta unos segundos; hacerlo en cada peticion volveria
    lento cada registro de compra. El candado evita que dos peticiones
    simultaneas construyan dos motores. El motor con clasificacion de angulo
    solo se construye si alguna foto ilegible obliga a reintentar, asi que la
    mayoria de las peticiones nunca paga su carga.
    """
    motor = _motores.get(usar_orientacion)
    if motor is not None:
        return motor

    with _candado:
        if usar_orientacion not in _motores:
            _motores[usar_orientacion] = _construir_motor(usar_orientacion)
        return _motores[usar_orientacion]


def preparar_imagen_para_ocr(imagen, max_lado=MAX_LADO_OCR):
    """Endereza por EXIF y reduce la foto antes del OCR sin perder texto."""
    imagen = ImageOps.exif_transpose(imagen)
    if imagen.mode != 'RGB':
        imagen = imagen.convert('RGB')
    if max(imagen.size) > max_lado:
        imagen.thumbnail((max_lado, max_lado), Image.LANCZOS)
    return ImageOps.autocontrast(imagen, cutoff=1)


def _imagen_desde_bytes(contenido):
    with Image.open(io.BytesIO(contenido)) as imagen:
        imagen.load()
        return preparar_imagen_para_ocr(imagen)


def leer_texto(contenido, usar_orientacion=False):
    """
    Extrae el texto de una imagen.

    Devuelve (lineas, error). Nunca lanza: si el OCR falla, se devuelve el error
    y el llamador decide. Quien decide es _validar_comprobante(), que en modo
    estricto RECHAZA la foto si no se pudo leer: no se acepta ninguna imagen
    solo porque el motor este caido, porque eso abriria la puerta a guardar
    compras sin evidencia verificada.

    usar_orientacion activa la clasificacion de angulo, que cuesta tiempo pero
    endereza fotos tomadas al reves. Solo se pide en el reintento de las fotos
    que salieron ilegibles.
    """
    inicio = time.perf_counter()
    try:
        if isinstance(contenido, Image.Image):
            imagen = preparar_imagen_para_ocr(contenido)
        else:
            imagen = _imagen_desde_bytes(contenido)
    except Exception as error:
        return [], f"No se pudo preparar la imagen para el lector de texto: {error}"
    ms_preparacion = (time.perf_counter() - inicio) * 1000

    try:
        motor = obtener_motor(usar_orientacion)
    except OCRNoDisponible as error:
        return [], str(error)

    try:
        with _semaforo_ocr:
            inicio_ocr = time.perf_counter()
            salida = motor(imagen)
            ms_ocr = (time.perf_counter() - inicio_ocr) * 1000
    except Exception as error:
        return [], f"El lector de texto fallo: {error}"

    _log.info(
        "OCR: preparacion %.0f ms, inferencia %.0f ms, imagen %sx%s, orientacion %s",
        ms_preparacion, ms_ocr, imagen.width, imagen.height,
        'si' if usar_orientacion else 'no',
    )
    # RapidOCR 3.x devuelve un objeto con .txts; las versiones previas
    # devolvian una tupla. Se cubren las dos.
    lineas = getattr(salida, 'txts', None)
    if lineas is None:
        lineas = _textos_de_estructura_desconocida(salida)

    return [linea for linea in lineas if str(linea).strip()], None


def _textos_de_estructura_desconocida(salida):
    """Recorre la respuesta buscando los textos, sea cual sea su forma."""
    encontrados = []

    def recorrer(objeto, profundidad=0):
        if profundidad > 6:
            return
        if isinstance(objeto, str):
            if objeto.strip():
                encontrados.append(objeto.strip())
        elif isinstance(objeto, (list, tuple)):
            for parte in objeto:
                recorrer(parte, profundidad + 1)

    recorrer(salida)
    return encontrados


def limpiar_para_evaluar(lineas):
    """Minusculas y sin acentos, para que las reglas no dependan de la tilde."""
    texto = ' '.join(str(linea) for linea in lineas)
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).lower()
