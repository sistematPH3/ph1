import threading
import io
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import current_user
from sqlalchemy import func
from datetime import datetime
from app.logistics.requests.purchase_request import PurchaseRequest
from app.logistics.services.purchase_service import PurchaseService
from app import db 
from app.models.inventory_model import Product
from app.models.security_model import User  
from app.models.logistics_model import Supplier, Purchase, PurchaseDetail, ExchangeRateHistory
from app.integrations.imgbb.imgbb_services import upload_invoice_image

purchase_bp = Blueprint('purchase_routes', __name__)

def bg_upload_invoice(app_instance, purchase_id, file_bytes, filename):
    """
    Función que se ejecuta en segundo plano para subir la imagen a ImgBB
    y actualizar la URL real en la base de datos de forma silenciosa.
    """
    # Levantamos el contexto de la aplicación en el hilo secundario
    with app_instance.app_context():
        try:
            # Reconstruimos el archivo en memoria usando los bytes guardados
            foto_factura_memoria = io.BytesIO(file_bytes)
            foto_factura_memoria.filename = filename
            
            # Subir a ImgBB de forma asíncrona respecto al usuario
            url_generada = upload_invoice_image(foto_factura_memoria)
            
            # Buscamos la compra creada previamente y actualizamos su URL
            purchase = Purchase.query.get(purchase_id)
            if purchase:
                purchase.invoice_url = url_generada
                db.session.commit()
                print(f"[BACKGROUND] URL de factura actualizada con éxito para la compra ID: {purchase_id}")
        except Exception as e:
            db.session.rollback()
            print(f"[BACKGROUND ERROR] Falló la subida de imagen para la compra ID {purchase_id}: {str(e)}")


@purchase_bp.route('/purchases/new', methods=['GET'])
def new_purchase_form():
    products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
    suppliers = Supplier.query.filter(func.upper(Supplier.status).in_(['ACTIVE', 'ACTIVO', 'OPERATIVO', 'OPERATIVA'])).order_by(Supplier.name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()
    
    return render_template(
        'logistics/register_purchase.html', 
        products=products, 
        suppliers=suppliers, 
        users=users
    )

@purchase_bp.route('/purchases/<int:purchase_id>', methods=['GET'])
def view_purchase_details(purchase_id):
    purchase = Purchase.query.get_or_404(purchase_id)
    supplier = Supplier.query.get(purchase.supplier_id)
    user = User.query.get(purchase.user_id)
    
    details = db.session.query(PurchaseDetail, Product.name)\
        .join(Product, PurchaseDetail.product_id == Product.id)\
        .filter(PurchaseDetail.purchase_id == purchase_id).all()
    
    rate_history = ExchangeRateHistory.query\
        .filter_by(currency=purchase.currency)\
        .order_by(ExchangeRateHistory.timestamp.desc())\
        .limit(5).all()
    
    return render_template(
        'logistics/purchase_details.html', 
        purchase=purchase, 
        details=details,
        rate_history=rate_history,
        supplier=supplier,
        user=user
    )

@purchase_bp.route('/purchases', methods=['POST'])
def create_purchase():
    try:
        foto_factura = request.files.get('invoice_photo')
        if not foto_factura or foto_factura.filename == '':
            return jsonify({"error": "Debe adjuntar la foto de la factura."}), 400

        # =====================================================================
        # PASO 1: Extraer los bytes e información del archivo de inmediato.
        # Esto evita que los datos se pierdan al responder al cliente.
        # =====================================================================
        file_bytes = foto_factura.read()
        filename = foto_factura.filename

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
        
        # Guardamos provisionalmente un texto indicador mientras se sube la imagen
        data = {
            'supplier_id': request.form.get('supplier_id', type=int),
            'currency': request.form.get('currency'),
            'exchange_rate': request.form.get('exchange_rate', type=float),
            'user_id': current_user.id if current_user.is_authenticated else (request.form.get('user_id', type=int) or 1),
            'invoice_url': 'Subiendo comprobante...', 
            'items': items
        }
    except Exception as e:
        return jsonify({"error": "Error al procesar los campos del formulario.", "details": str(e)}), 400

    if not data:
        return jsonify({"error": "No se recibieron datos en la petición."}), 400

    is_valid, errors = PurchaseRequest.validate_create(data)
    if not is_valid:
        return jsonify({"error": "Datos inválidos", "details": errors}), 400

    # Guardamos la compra de manera atómica y segura en base de datos
    result = PurchaseService.register_purchase(data)

    if result["success"]:
        try:
            historial_tasa = ExchangeRateHistory(
                currency=data['currency'],
                rate=data['exchange_rate'],
                source='COMPRA REGISTRADA',
                timestamp=datetime.now(),
                user_id=data['user_id']
            )
            db.session.add(historial_tasa)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            
        # =====================================================================
        # PASO 2: Disparar el Hilo secundario para subir la imagen a ImgBB
        # =====================================================================
        # Obtenemos la instancia real de la app detrás del proxy current_app
        app_instance = current_app._get_current_object()
        purchase_id = result["purchase_id"]
        
        thread = threading.Thread(
            target=bg_upload_invoice,
            args=(app_instance, purchase_id, file_bytes, filename)
        )
        thread.start()

        # Respondemos INSTANTÁNEAMENTE al frontend
        return jsonify(result), 201
    else:
        return jsonify(result), 500