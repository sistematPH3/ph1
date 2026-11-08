import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
import os
import sys

# 1. Ajustar el path para que el script pueda encontrar tu carpeta 'app'
# Esto asume que tasks_bcv.py está en app/integrations/api_bcv/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from app import create_app, db
from app.models import ExchangeRateHistory

def obtener_y_guardar_tasas():
    app = create_app()
    with app.app_context(): # Esto es vital para que la BD funcione
        scraper = cloudscraper.create_scraper()
        url = "https://www.bcv.org.ve/"
        
        try:
            print("Conectando al BCV...")
            response = scraper.get(url, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                dolar_div = soup.find('div', id='dolar')
                euro_div = soup.find('div', id='euro')
                
                tasa_usd = float(dolar_div.find('strong').text.strip().replace(',', '.'))
                tasa_eur = float(euro_div.find('strong').text.strip().replace(',', '.'))
                
                # Guardamos en la BD
                nueva_tasa_usd = ExchangeRateHistory(currency='USD', rate=tasa_usd, source='BCV', timestamp=datetime.now(), user_id=1)
                nueva_tasa_eur = ExchangeRateHistory(currency='EUR', rate=tasa_eur, source='BCV', timestamp=datetime.now(), user_id=1)
                
                db.session.add(nueva_tasa_usd)
                db.session.add(nueva_tasa_eur)
                db.session.commit()
                
                print(f"Tasas guardadas exitosamente: USD={tasa_usd}, EUR={tasa_eur}")
            else:
                print(f"Error HTTP: {response.status_code}")
            
        except Exception as e:
            print(f"Error al guardar: {e}")

if __name__ == "__main__":
    obtener_y_guardar_tasas()