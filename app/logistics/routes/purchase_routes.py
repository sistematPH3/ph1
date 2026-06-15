# app/logistics/routes/purchase_routes.py
from flask import Blueprint, request, jsonify, render_template
from app.logistics.requests.purchase_request import PurchaseRequest
from app.logistics.services.purchase_service import PurchaseService

purchase_bp = Blueprint('purchase_routes', __name__)

@purchase_bp.route('/purchases/new', methods=['GET'])
def new_purchase_form():
    return render_template('logistics/register_purchase.html')

@purchase_bp.route('/purchases', methods=['POST'])
def create_purchase():
    # Detectamos si la petición viene como JSON o como formulario tradicional
    if request.is_json:
        data = request.get_json()
    else:
        # Si es un formulario HTML clásico, estructuramos el diccionario mapeando los arreglos
        try:
            product_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            foreign_prices = request.form.getlist('foreign_price[]')
            
            items = []
            for i in range(len(product_ids)):
                items.append({
                    'product_id': int(product_ids[i]) if product_ids[i] else None,
                    'quantity': float(quantities[i]) if quantities[i] else 0.0,
                    'foreign_price': float(foreign_prices[i]) if foreign_prices[i] else 0.0
                })
            
            data = {
                'supplier_id': request.form.get('supplier_id', type=int),
                'currency': request.form.get('currency'),
                'exchange_rate': request.form.get('exchange_rate', type=float),
                'user_id': request.form.get('user_id', type=int) or 1, # ID temporal o de sesión
                'invoice_url': request.form.get('invoice_url'),
                'items': items
            }
        except Exception as e:
            return jsonify({"error": "Error al procesar los campos del formulario.", "details": str(e)}), 400

    if not data:
        return jsonify({"error": "No se recibieron datos en la petición."}), 400

    # 1. Validar los datos de entrada de forma segura
    is_valid, errors = PurchaseRequest.validate_create(data)
    if not is_valid:
        return jsonify({"error": "Datos inválidos", "details": errors}), 400

    # 2. Ejecutar la transacción en la capa de servicios
    result = PurchaseService.register_purchase(data)

    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 500