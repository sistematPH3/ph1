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
        response = requests.post(url, data=payload, files=files)
        response.raise_for_status() 
        
        data = response.json()
        
        if data.get("success"):
            return data["data"]["url"]
        else:
            error_msg = data.get('error', {}).get('message', 'Error desconocido')
            raise Exception(f"La API de ImgBB rechazó la imagen: {error_msg}")
            
    except requests.exceptions.RequestException as e:
        raise Exception(f"Fallo de conexión al intentar subir la evidencia: {str(e)}")