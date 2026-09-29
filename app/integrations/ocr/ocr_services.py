"""
Lectura de texto de la foto de la factura, en local y sin internet.

Usa RapidOCR (Apache-2.0), que es motor de ONNX: no necesita PyTorch ni
PyGoogle. El modelo se descarga una sola vez al instalar y queda en
.venv/lib/.../rapidocr/models, asi que despues funciona sin conexion.

Se expone solo texto. La decision de si esa foto es una factura no se toma
aqui, sino en PurchaseValidator, que son reglas puras y testeables.
"""
import logging
import re
import threading
import unicodedata

_motor = None
_candado = threading.Lock()

# RapidOCR escribe un INFO por cada modelo que carga. En un servidor con
# peticiones concurrentes eso llena el log de ruido.
logging.getLogger('rapidocr').setLevel(logging.ERROR)


class OCRNoDisponible(RuntimeError):
    """El motor de OCR no se pudo cargar. El flujo debe continuar sin el."""


def _construir_motor():
    try:
        from rapidocr import RapidOCR
    except ImportError as error:
        raise OCRNoDisponible(
            "RapidOCR no esta instalado. Instale con 'pip install rapidocr onnxruntime'."
        ) from error

    try:
        return RapidOCR()
    except ImportError as error:
        # rapidocr no declara onnxruntime como dependencia: es un extra, y sin
        # el la inicializacion falla con un ImportError poco descriptivo.
        raise OCRNoDisponible(
            "Falta onnxruntime, que rapidocr no instala solo. "
            "Instalelo con 'pip install onnxruntime'."
        ) from error
    except Exception as error:
        raise OCRNoDisponible(f"No se pudo iniciar el motor de OCR: {error}") from error


def obtener_motor():
    """
    Devuelve el motor ya inicializado, creandolo en la primera llamada.

    Cargar los modelos cuesta unos segundos; hacerlo en cada peticion volveria
    lento cada registro de compra. El candado evita que dos peticiones
    simultaneas construyan dos motores.
    """
    global _motor
    if _motor is not None:
        return _motor

    with _candado:
        if _motor is None:
            _motor = _construir_motor()
    return _motor


def leer_texto(contenido: bytes):
    """
    Extrae el texto de una imagen.

    Devuelve (lineas, error). Nunca lanza: si el OCR falla, se devuelve el error
    y el llamador decide. Quien decide es _validar_comprobante(), que en modo
    estricto RECHAZA la foto si no se pudo leer: no se acepta ninguna imagen
    solo porque el motor este caido, porque eso abriria la puerta a guardar
    compras sin evidencia verificada.
    """
    try:
        motor = obtener_motor()
    except OCRNoDisponible as error:
        return [], str(error)

    # RapidOCR acepta bytes, ndarray, ruta o PIL.Image; un BytesIO lo rechaza.
    try:
        salida = motor(contenido)
    except Exception as error:
        return [], f"El lector de texto fallo: {error}"
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
