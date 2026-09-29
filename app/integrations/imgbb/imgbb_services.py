import os
import requests
from werkzeug.datastructures import FileStorage

def upload_invoice_image(image_file: FileStorage) -> str:
    """
    Recibe la foto de la factura desde el frontend, 
    la envía a la API de ImgBB y retorna la URL segura generada.
    """
    api_key = os.getenv('IMGBB_API_KEY')
    if not api_key:
        raise ValueError("Error de configuración: IMGBB_API_KEY no encontrada en el .env")

    url = "https://api.imgbb.com/1/upload"

    payload = {
        "key": api_key
    }
    
    files = {
        "image": image_file.read()
    }

    try:
        # Sin timeout la llamada se queda colgada para siempre si ImgBB no
        # responde. Esta subida corre en un hilo de fondo, asi que el cuelgue
        # no bloquea la compra, pero si acumulara hilos y conexiones
        # abiertas cada vez que se registra una compra sin salida a internet.
        response = requests.post(url, data=payload, files=files, timeout=20)
        response.raise_for_status()

        data = response.json()

        if data.get("success"):
            return data["data"]["url"]
        else:
            error_msg = data.get('error', {}).get('message', 'Error desconocido')
            raise Exception(f"La API de ImgBB rechazó la imagen: {error_msg}")

    except ValueError:
        # response.json() sobre un cuerpo que no es JSON (pagina de error en
        # HTML, vacio, o un proxy cortando la conexion) lanza ValueError, que
        # here NO es de tipo: salia del except de abajo y se perdia el
        # motivo real del fallo.
        raise Exception(
            "ImgBB devolvió una respuesta ilegible al subir la evidencia."
        )
    except requests.exceptions.RequestException as e:
        raise Exception(f"Fallo de conexión al intentar subir la evidencia: {str(e)}")
