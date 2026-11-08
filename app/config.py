import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))


load_dotenv(os.path.join(basedir, '../.env'))


def _base_de_datos_segura():
    """Muestra el origen de datos sin exponer usuario ni contrasena en los logs."""
    url = os.environ.get('DATABASE_URL')
    if not url:
        return '(sin configurar)'
    return url.rsplit('@', 1)[-1] if '@' in url else '(configuracion invalida)'


print(f"DEBUG: base de datos -> {_base_de_datos_segura()}")


class ConfigError(RuntimeError):
    """Falta una variable de entorno imprescindible para arrancar."""


def _exigida(nombre):
    valor = os.environ.get(nombre)
    if not valor:
        raise ConfigError(
            f"Falta la variable de entorno {nombre}. "
            "Definela en el archivo .env; no se usan valores por defecto inseguros."
        )
    return valor


class Config:
    # Sin fallback: una clave secreta publica permite falsificar sesiones y cookies.
    SECRET_KEY = _exigida('SECRET_KEY')

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- SMTP (recuperacion de contrasena) -------------------------------
    # Todo sale del entorno: el codigo ya no lleva credenciales ni hosts.
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '465'))
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'true').strip().lower() in ('1', 'true', 'yes', 'si')
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').strip().lower() in ('1', 'true', 'yes', 'si')
    MAIL_TIMEOUT = int(os.environ.get('MAIL_TIMEOUT', '15'))

    # --- Enlaces de recuperacion -----------------------------------------
    # URL publica del sistema. Si se define, se usa como host del enlace del
    # correo; si no, se deriva de la peticion (_external=True).
    PUBLIC_BASE_URL = (os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')

    # --- Limites de la recuperacion --------------------------------------
    RECUPERACION_VIGENCIA_HORAS = int(os.environ.get('RECUPERACION_VIGENCIA_HORAS', '1'))
    RECUPERACION_MAX_INTENTOS = int(os.environ.get('RECUPERACION_MAX_INTENTOS', '5'))
    RECUPERACION_VENTANA_SEGUNDOS = int(os.environ.get('RECUPERACION_VENTANA_SEGUNDOS', '900'))

    # --- Limites de las fotos de evidencia --------------------------------
    # Tope de la peticion completa. Antes no existia ninguno y las rutas hacian
    # archivo.read(): un adjunto grande tumbaba el servidor por falta de memoria.
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', str(10 * 1024 * 1024)))

    # Modo del validador de facturas. NO es un interruptor para saltarse la
    # foto: la evidencia es obligatoria siempre y la compra se detiene si el
    # OCR no confirma un comprobante de compra, este en el modo que sea. El
    # valor queda como referencia de como se evaluo y se audita.
    INVOICE_VALIDATION_MODE = os.environ.get('INVOICE_VALIDATION_MODE', 'strict').strip().lower()
    INVOICE_UMBRAL_ACEPTACION = int(os.environ.get('INVOICE_UMBRAL_ACEPTACION', '60'))


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
