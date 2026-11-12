# app/utils/storage.py
import boto3
import logging
import os
from flask import current_app

logger = logging.getLogger(__name__)

def get_s3_client():
    """
    Configura y retorna el cliente de conexión para Backblaze B2.
    Utiliza las credenciales definidas en el archivo .env.
    """
    return boto3.client(
        's3',
        endpoint_url=os.environ.get('B2_ENDPOINT'),
        aws_access_key_id=os.environ.get('B2_KEY_ID'),
        aws_secret_access_key=os.environ.get('B2_APPLICATION_KEY')
    )

def subir_factura(file_stream, filename):
    """
    Sube un archivo (factura, guía o reporte) al bucket de B2.
    
    :param file_stream: El objeto del archivo a subir (ej: request.files['file'])
    :param filename: El nombre que tendrá el archivo en la nube
    :return: True si fue exitoso, False en caso contrario
    """
    s3 = get_s3_client()
    try:
        s3.upload_fileobj(
            file_stream, 
            os.environ.get('B2_BUCKET_NAME'), 
            filename
        )
        return True
    except Exception:
        # El detalle técnico queda en el log; al llamador se le sigue
        # devolviendo False igual que antes.
        logger.exception("Error técnico al subir %s a B2", filename)
        return False