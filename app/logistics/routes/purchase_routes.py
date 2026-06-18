from flask import Blueprint, request, jsonify, render_template
from app.logistics.requests.purchase_request import PurchaseRequest
from app.logistics.services.purchase_service import PurchaseService
# IMPORTAMOS TU INSTANCIA DE BASE DE DATOS (Ajusta la ruta si la importan de otro lado)
from app import db 
# IMPORTAMOS LOS MODELOS NECESARIOS
from app.models.inventory_model import Product
from app.models.security_model import User  
from app.models.logistics_model import Supplier
# === AÑADE ESTA LÍNEA PARA LOS MODELOS DEL SUB-MÓDULO 5 ===
# (Asegúrate de que los nombres coincidan exactamente con las clases en tu logistics_model)
from app.models.logistics_model import Purchase, PurchaseDetail, ExchangeRateHistory
from app.models.security_model import User
from app.integrations.imgbb.imgbb_services import upload_invoice_image

purchase_bp = Blueprint('purchase_routes', __name__)

@purchase_bp.route('/purchases/new', methods=['GET'])
def new_purchase_form():
    products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
    suppliers = Supplier.query.filter_by(status='Active').order_by(Supplier.name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()
    
    return render_template(
        'logistics/register_purchase.html', 
        products=products, 
        suppliers=suppliers, 
        users=users
    )
@purchase_bp.route('/purchases/<int:purchase_id>', methods=['GET'])
# Si usas flask_login, puedes descomentar la siguiente línea:
# @login_required
def view_purchase_details(purchase_id):
    # 1. Buscar la cabecera de la compra. Si no existe, envía un error 404 estructurado.
    purchase = Purchase.query.get_or_404(purchase_id)
    # 2. Buscar el proveedor y el usuario usando los IDs de la compra
    # Esto repara el problema de que salgan en 'N/A' y 'Sistema'
    supplier = Supplier.query.get(purchase.supplier_id)
    user = User.query.get(purchase.user_id)
    
    # 2. Consultar los renglones (detalles) cruzando con el nombre del Producto
    details = db.session.query(PurchaseDetail, Product.name)\
        .join(Product, PurchaseDetail.product_id == Product.id)\
        .filter(PurchaseDetail.purchase_id == purchase_id).all()
    
    # 3. Traer las últimas 5 tasas históricas de la moneda de esta factura para el panel de Lemin
    rate_history = ExchangeRateHistory.query\
        .filter_by(currency=purchase.currency)\
        .order_by(ExchangeRateHistory.timestamp.desc())\
        .limit(5).all()
    
    # 4. Renderizar la plantilla pasándole todas las variables necesarias
    return render_template(
        'logistics/purchase_details.html', 
        purchase=purchase, 
        details=details,
        rate_history=rate_history,
        supplier=supplier,  # <-- Enviado de forma independiente
        user=user
    )

@purchase_bp.route('/purchases', methods=['POST'])
def create_purchase():
    try:
        foto_factura = request.files.get('invoice_photo')
        if not foto_factura or foto_factura.filename == '':
            return jsonify({"error": "Debe adjuntar la foto de la factura."}), 400

        url_generada = upload_invoice_image(foto_factura)

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
            'user_id': request.form.get('user_id', type=int) or 1,
            'invoice_url': url_generada,
            'items': items
        }
    except Exception as e:
        return jsonify({"error": "Error al procesar los campos del formulario.", "details": str(e)}), 400

    if not data:
        return jsonify({"error": "No se recibieron datos en la petición."}), 400

    is_valid, errors = PurchaseRequest.validate_create(data)
    if not is_valid:
        return jsonify({"error": "Datos inválidos", "details": errors}), 400

    result = PurchaseService.register_purchase(data)

    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 500