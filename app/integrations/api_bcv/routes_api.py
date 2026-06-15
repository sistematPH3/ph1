from flask import Blueprint, jsonify, request, render_template
from flask_login import current_user
from app.extensions import db
from app.models.logistics_model import ExchangeRateHistory
from datetime import datetime
import requests

# Definimos el Blueprint para la API del BCV
api_bcv_bp = Blueprint('api_bcv', __name__)

# ==========================================
# 1. RUTA PARA RENDERIZAR EL FORMULARIO
# ==========================================
@api_bcv_bp.route('/prueba-bcv', methods=['GET'])
def vista_prueba_bcv():
    return render_template('prueba_bcv.html')

# ==========================================
# 2. ENDPOINT API: OBTENER TASA (ESTRICTO)
# ==========================================
@api_bcv_bp.route('/api/get-rate', methods=['GET'])
def get_bcv_rate():
    """
    Obtiene la tasa oficial usando 'requests'. 
    Si la red local tiene restricciones, retornará 503 para 
    activar el modo manual en el frontend.
    """
    currency = request.args.get('currency', 'USD').upper()
    
    try:
        # Petición a la API espejo
        response = requests.get(
            "https://ve.descubra.me/api/v1/bcv/latest", 
            timeout=5,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        response.raise_for_status()
        data = response.json()
        
        # Extraer tasa según moneda
        rate_float = float(data['monedas'][currency]['valor'])
        
        # Auditoría: Guardar en base de datos
        try:
            user_id = current_user.id if hasattr(current_user, 'id') else 1 
            nuevo_historial = ExchangeRateHistory(
                currency=currency,
                rate=rate_float,
                source='BCV_Oficial',
                timestamp=datetime.now(),
                user_id=user_id
            )
            db.session.add(nuevo_historial)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error de BD: {e}")

        return jsonify({
            'success': True,
            'rate': rate_float,
            'source': 'BCV_Oficial'
        }), 200

    except Exception as e:
        print(f"Error de conexión: {str(e)}")
        # Retornamos error 503 para que el frontend habilite la edición manual
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servidor BCV.'
        }), 503