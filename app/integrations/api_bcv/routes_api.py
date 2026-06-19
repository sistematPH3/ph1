from flask import Blueprint, jsonify, request, render_template
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

api_bcv_bp = Blueprint('api_bcv', __name__)

def get_bcv_rate_from_web(currency):
    """Consulta la tasa en la web del BCV para USD o EUR."""
    url = "https://www.bcv.org.ve/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Mapeo de moneda a ID en el HTML del BCV
        target_id = 'dolar' if currency == 'USD' else 'euro'
        rate_div = soup.find('div', id=target_id)
        
        if rate_div:
            rate_str = rate_div.find('strong').text.strip().replace(',', '.')
            return float(rate_str)
    except Exception as e:
        print(f"Error scraping BCV: {e}")
    return None

@api_bcv_bp.route('/prueba-bcv', methods=['GET'])
def vista_prueba_bcv():
    return render_template('prueba_bcv.html')

@api_bcv_bp.route('/api/get-rate', methods=['GET'])
def get_bcv_rate():
    currency = request.args.get('currency', 'USD')
    rate = get_bcv_rate_from_web(currency)
    
    if rate:
        return jsonify({'success': True, 'rate': rate, 'source': 'BCV_Web'}), 200
    
    return jsonify({'success': False, 'message': 'No se pudo conectar.'}), 503