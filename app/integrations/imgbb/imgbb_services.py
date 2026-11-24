import os

import requests

URL_SUBIDA = "https://api.imgbb.com/1/upload"
TIMEOUT_SUBIDA = (10, 30)

MIME_POR_EXTENSION = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def _firma(contenido):
    if contenido[:3] == b'\xff\xd8\xff':
        return '.jpg', 'image/jpeg'
    if contenido[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png', 'image/png'
    if contenido[:4] == b'RIFF' and contenido[8:12] == b'WEBP':
        return '.webp', 'image/webp'
    return '.jpg', 'image/jpeg'


def _nombre_y_mime(archivo, contenido):
    """
    Nombre con extension y tipo MIME reales.

    Antes se mandaban los bytes sueltos: requests los subia como un archivo
    llamado "image" sin tipo MIME y ImgBB tenia que adivinar el formato. Si no
    lo reconocia, respondia un error que aqui se perdia y la foto quedaba sin
    guardar. Ahora el formato viaja explicito, tomado del nombre o, si no lo
    tiene, de los primeros bytes del archivo.
    """
    nombre = os.path.basename(getattr(archivo, 'filename', '') or '') or 'comprobante'
    raiz, extension = os.path.splitext(nombre)
    extension = extension.lower()
    tipo_mime = MIME_POR_EXTENSION.get(extension)
    if not tipo_mime:
        extension, tipo_mime = _firma(contenido)
    return f"{raiz or 'comprobante'}{extension}", tipo_mime


def upload_invoice_image(image_file) -> str:
    """Sube la foto del comprobante a ImgBB y devuelve su URL publica."""
    api_key = os.getenv('IMGBB_API_KEY')
    if not api_key:
        raise ValueError(
            "Error de configuración: IMGBB_API_KEY no encontrada en el .env")

    if hasattr(image_file, 'seek'):
        image_file.seek(0)
    contenido = image_file.read() if hasattr(image_file, 'read') else image_file
    if not contenido:
        raise ValueError(
            "La foto del comprobante llegó vacía al servidor de imágenes.")

    nombre, tipo_mime = _nombre_y_mime(image_file, contenido)

    try:
        response = requests.post(
            URL_SUBIDA,
            data={"key": api_key},
            files={"image": (nombre, contenido, tipo_mime)},
            timeout=TIMEOUT_SUBIDA,
        )
    except requests.exceptions.RequestException as error:
        raise Exception(
            f"Fallo de conexión al intentar subir la evidencia: {error}") from error

    estado = getattr(response, 'status_code', 'sin estado')
    try:
        cuerpo = response.json()
    except ValueError:
        raise Exception(
            "ImgBB devolvió una respuesta ilegible al subir la evidencia "
            f"(HTTP {estado}).")

    if not isinstance(cuerpo, dict) or not cuerpo.get("success"):
        detalle = ((cuerpo or {}).get('error') or {}).get('message') \
            if isinstance(cuerpo, dict) else None
        raise Exception(
            f"La API de ImgBB rechazó la imagen (HTTP {estado}): "
            f"{detalle or 'sin detalle'}")

    url = ((cuerpo.get('data') or {}).get('url') or '').strip()
    if not url:
        raise Exception("ImgBB aceptó la subida pero no devolvió ninguna URL.")
    return url
