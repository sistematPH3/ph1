import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
import os
import sys
import urllib3

# El certificado del BCV no valida en algunos entornos (igual que en
# routes_api.get_bcv_rate_from_web, que ya usa verify=False).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# 1. Ajustar el path para que el script pueda encontrar tu carpeta 'app'
# Esto asume que tasks_bcv.py está en app/integrations/api_bcv/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from app import create_app, db
from app.models import ExchangeRateHistory
from app.models.security_model import User
# Único punto de conversión de tasas del BCV. Antes había una copia de esta
# función aquí y otra en routes_api: un arreglo en una no llegaba a la otra y
# el EUR se seguía guardando mal por el script manual.
from app.integrations.api_bcv.routes_api import DIVISAS_BCV, _tasa_bcv_a_float


def _extraer_tasas(soup):
    """Tasas publicadas por el BCV, divisa por divisa.

    Cada moneda se lee y parsea de forma independiente: antes se parseaban
    ambas y después se insertaban juntas, así que un fallo con la tasa EUR
    abortaba el guardado completo y tampoco se registraba el USD; la serie EUR
    quedaba vacía y todos los montos en euros del reporte caían a 0.
    """
    tasas = {}
    for moneda, div_id in DIVISAS_BCV.items():
        bloque = soup.find('div', id=div_id)
        try:
            if bloque is None or bloque.find('strong') is None:
                raise ValueError('el BCV no publicó el bloque #' + div_id)
            tasas[moneda] = _tasa_bcv_a_float(bloque.find('strong').text)
        except (AttributeError, TypeError, ValueError):
            logger.exception("No se pudo leer la tasa %s del BCV", moneda)
    return tasas


def obtener_y_guardar_tasas(user_id=None):
    app = create_app()
    with app.app_context(): # Esto es vital para que la BD funcione
        # Mismo cliente y cabeceras que routes_api.get_bcv_rate_from_web, que
        # sí logra leer la página; cloudscraper fallaba por SSL.
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                 'AppleWebKit/537.36 (KHTML, like Gecko) '
                                 'Chrome/120.0.0.0 Safari/537.36'}
        url = "https://www.bcv.org.ve/"
        
        try:
            print("Conectando al BCV...")
            response = requests.get(url, headers=headers, timeout=15,
                                    verify=False)
            if response.status_code == 200:
                if user_id is None:
                    # user_id es NOT NULL con FK a users: el 1 fijo reventaba el
                    # INSERT en instalaciones donde el admin tiene otro id.
                    usuario = User.query.order_by(User.id).first()
                    if usuario is None:
                        logger.error("No hay usuarios para archivar las tasas del BCV.")
                        return
                    user_id = usuario.id
                soup = BeautifulSoup(response.text, 'html.parser')
                tasas = _extraer_tasas(soup)
                if not tasas:
                    logger.error("El BCV no publicó ninguna tasa legible; "
                                 "no se guardó nada.")
                    return

                # Se guarda cada tasa leída: si el BCV no publicó una divisa, la
                # otra igual queda registrada en exchange_rate_history.
                momento = datetime.now()
                for moneda, tasa in tasas.items():
                    db.session.add(ExchangeRateHistory(
                        currency=moneda, rate=tasa, source='BCV',
                        timestamp=momento, user_id=user_id))
                db.session.commit()

                print("Tasas guardadas exitosamente: " + ", ".join(
                    '{0}={1}'.format(moneda, tasa)
                    for moneda, tasa in tasas.items()))
            else:
                print(f"Error HTTP: {response.status_code}")
            
        except Exception:
            logger.exception("Error al obtener y guardar las tasas del BCV")

if __name__ == "__main__":
    obtener_y_guardar_tasas()