from flask import Blueprint, jsonify, request
from flask_login import current_user
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import urllib3

from app import db
from app.models import ExchangeRateHistory
from app.decorators.roles import admin_required, require_roles_api


def _tasa_bcv_a_float(texto):
    """Convierte una tasa del BCV a float.

    Formato venezolano: punto para miles y coma para decimales
    ("1.007,38665582" -> 1007.38665582). Es el ÚNICO punto de conversión de
    tasas del BCV: tasks_bcv.py lo importa de aquí en vez de duplicarlo.
    """
    limpio = (texto or '').strip().replace(' ', '').replace('\xa0', '')
    if not limpio:
        raise ValueError('El BCV devolvió una tasa vacía.')
    if ',' in limpio:
        limpio = limpio.replace('.', '').replace(',', '.')
    return float(limpio)

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

api_bcv_bp = Blueprint('api_bcv', __name__)

DIVISAS_BCV = {'USD': 'dolar', 'EUR': 'euro'}


def get_bcv_rate_from_web(currency, timeout=10):
    """Consulta la tasa en la web del BCV para USD o EUR.

    ``timeout`` es configurable: la consulta desde Compras tolera esperar, pero
    los respaldos automáticos (Estadísticas, registro de compras) usan un
    timeout corto para no demorar la pantalla si el BCV está caído.
    """
    url = "https://www.bcv.org.ve/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    moneda = (currency or 'USD').upper()
    try:
        response = requests.get(url, headers=headers, timeout=timeout,
                                verify=False)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Mapeo de moneda a ID en el HTML del BCV
        target_id = DIVISAS_BCV.get(moneda)
        if target_id is None:
            return None
        rate_div = soup.find('div', id=target_id)

        if rate_div and rate_div.find('strong') is not None:
            return _tasa_bcv_a_float(rate_div.find('strong').text)
    except Exception as exc:
        logger.warning("Error scraping BCV (%s): %s", currency, exc)
    return None


def guardar_tasa(moneda, tasa, user_id, source='BCV'):
    """Archiva la tasa del día de forma IDEMPOTENTE.

    Si ya hay una fila de esa moneda con timestamp de hoy se actualiza el rate
    (el BCV publica una sola tasa diaria y varias consultas seguidas no deben
    inflar exchange_rate_history); si no existe, se inserta. En la actualización
    se conserva el `source` original: describe de dónde salió la fila y no debe
    cambiar porque un disparador distinto vuelva a leer la misma tasa.
    Devuelve la fila guardada o None si no hay tasa o usuario con el cual
    archivarla (la FK user_id es NOT NULL).
    """
    moneda = (moneda or 'USD').upper()
    if not tasa:
        return None
    if user_id is None:
        logger.warning("Sin user_id no se puede archivar la tasa %s.", moneda)
        return None
    inicio_dia = datetime.now().replace(hour=0, minute=0, second=0,
                                        microsecond=0)
    try:
        fila = ExchangeRateHistory.query.filter(
            ExchangeRateHistory.currency == moneda,
            ExchangeRateHistory.timestamp >= inicio_dia,
        ).order_by(ExchangeRateHistory.timestamp.desc()).first()
        if fila is not None:
            fila.rate = tasa
        else:
            fila = ExchangeRateHistory(
                currency=moneda, rate=tasa, source=source,
                timestamp=datetime.now(), user_id=user_id)
            db.session.add(fila)
        db.session.commit()
        return fila
    except Exception:
        db.session.rollback()
        logger.exception("No se pudo archivar la tasa %s del BCV.", moneda)
        return None


@api_bcv_bp.route('/prueba-bcv', methods=['GET'])
@admin_required
def vista_prueba_bcv():
    """Diagnóstico de la consulta al BCV en JSON.

    Antes renderizaba 'prueba_bcv.html', una plantilla que no existe: la ruta
    respondía 500. Ahora devuelve el estado de USD y EUR sin depender de HTML.
    """
    timeout = request.args.get('timeout', type=float) or 5
    estado = {}
    for moneda in DIVISAS_BCV:
        tasa = get_bcv_rate_from_web(moneda, timeout=timeout)
        estado[moneda] = {'ok': tasa is not None, 'rate': tasa}
    todo_ok = all(dato['ok'] for dato in estado.values())
    return jsonify({
        'success': todo_ok,
        'source': 'BCV_Web',
        'tasas': estado,
        'message': ('Tasas leídas del BCV.' if todo_ok else
                    'El BCV no publicó alguna de las tasas.'),
    }), (200 if todo_ok else 503)


@api_bcv_bp.route('/api/get-rate', methods=['GET'])
@require_roles_api('admin', 'management', 'manager')
def get_bcv_rate():
    currency = (request.args.get('currency') or 'USD').upper()
    timeout = request.args.get('timeout', type=float) or 10
    rate = get_bcv_rate_from_web(currency, timeout=timeout)

    if rate:
        # Cada consulta desde Compras deja la tasa del día archivada: la serie
        # EUR/BS se mantiene sola, sin depender de un script manual.
        if current_user.is_authenticated:
            guardar_tasa(currency, rate, current_user.id)
        return jsonify({'success': True, 'rate': rate, 'source': 'BCV_Web'}), 200

    return jsonify({'success': False, 'message': 'No se pudo conectar.'}), 503
