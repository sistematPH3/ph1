import threading
import io
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import current_user
from sqlalchemy import func
from datetime import datetime, timedelta
import pytz
from app.logistics.requests.purchase_request import PurchaseRequest
from app.logistics.services.purchase_service import PurchaseService
from app import db 
from app.models import ProductType
from app.models.inventory_model import Product
from app.models.security_model import User  
from app.models.logistics_model import Supplier, Purchase, PurchaseDetail, ExchangeRateHistory, PurchaseAuditLog
from app.integrations.imgbb.imgbb_services import upload_invoice_image
from app.decorators.roles import require_roles

purchase_bp = Blueprint('purchase_routes', __name__)

def bg_upload_invoice(app_instance, purchase_id, file_bytes, filename):
    with app_instance.app_context():
        try:
            foto_factura_memoria = io.BytesIO(file_bytes)
            foto_factura_memoria.filename = filename
            
            url_generada = upload_invoice_image(foto_factura_memoria)
            
            purchase = Purchase.query.get(purchase_id)
            if purchase:
                purchase.invoice_url = url_generada
                db.session.commit()
        except Exception as e:
            db.session.rollback()

@purchase_bp.route('/purchases/new', methods=['GET'])
@require_roles('admin', 'management', 'manager')
def new_purchase_form():
    products_query = db.session.query(Product, ProductType).outerjoin(
        ProductType, Product.product_type_id == ProductType.id
    ).filter(Product.is_active == True).order_by(Product.name.asc()).all()
    
    products = []
    for prod, ptype in products_query:
        products.append({
            'id': prod.id,
            'name': prod.name,
            'unit_of_measure': prod.unit_of_measure,
            'shelf_life_days': ptype.shelf_life_days if ptype else 0
        })
        
    suppliers = Supplier.query.filter(func.upper(Supplier.status).in_(['ACTIVE', 'ACTIVO', 'OPERATIVO', 'OPERATIVA'])).order_by(Supplier.name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()
    
    return render_template(
        'logistics/register_purchase.html', 
        products=products, 
        suppliers=suppliers, 
        users=users
    )

@purchase_bp.route('/purchases/<int:purchase_id>', methods=['GET'])
@require_roles('admin', 'management', 'manager')
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
        
    audit_log = None
    audit_user = None
    audit_timestamp_local = None
    
    if purchase.status == 'ANNULLED':
        audit_log = PurchaseAuditLog.query.filter_by(purchase_id=purchase_id, action_type='ANNULLED').order_by(PurchaseAuditLog.timestamp.desc()).first()
        if audit_log:
            audit_user = User.query.get(audit_log.user_id)
            if audit_log.timestamp:
                utc_tz = pytz.utc
                caracas_tz = pytz.timezone('America/Caracas')
                audit_utc = utc_tz.localize(audit_log.timestamp)
                audit_timestamp_local = audit_utc.astimezone(caracas_tz)
                
    edit_logs_raw = PurchaseAuditLog.query.filter_by(purchase_id=purchase_id, action_type='EDIT').order_by(PurchaseAuditLog.timestamp.asc()).all()
    edit_logs = []
    
    for log in edit_logs_raw:
        editor = User.query.get(log.user_id)
        local_time = log.timestamp - timedelta(hours=4) if log.timestamp else None
        reason = log.new_data.get('edit_reason', 'Edición sin motivo especificado') if log.new_data else 'Edición sin motivo especificado'
        
        changes = []
        prev = log.previous_data or {}
        curr = log.new_data or {}

        if prev.get('total_amount') != curr.get('total_amount'):
            changes.append({'field': 'Costo Total de la Factura', 'from': prev.get('total_amount'), 'to': curr.get('total_amount')})
        if prev.get('exchange_rate') != curr.get('exchange_rate'):
            changes.append({'field': 'Tasa de Cambio Aplicada', 'from': prev.get('exchange_rate'), 'to': curr.get('exchange_rate')})

        prev_details = {str(d.get('id', d.get('product_id'))): d for d in prev.get('details', [])}
        curr_details = {str(d.get('id', d.get('product_id'))): d for d in curr.get('details', [])}

        all_item_keys = set(list(prev_details.keys()) + list(curr_details.keys()))

        for key in all_item_keys:
            p_item = prev_details.get(key)
            c_item = curr_details.get(key)

            prod_id = p_item['product_id'] if p_item else c_item['product_id']
            product_obj = Product.query.get(prod_id)
            prod_name = product_obj.name if product_obj else f"Insumo ID {prod_id}"

            if not p_item and c_item:
                changes.append({'field': f'Insumo Añadido: {prod_name}', 'from': '-', 'to': f"Cant. Comprada: {c_item.get('quantity')} | Precio Unitario: {c_item.get('foreign_price')}"})
            elif p_item and not c_item:
                changes.append({'field': f'Insumo Eliminado: {prod_name}', 'from': f"Cant. Comprada: {p_item.get('quantity')} | Precio Unitario: {p_item.get('foreign_price')}", 'to': '-'})
            else:
                if str(float(p_item.get('quantity', 0))) != str(float(c_item.get('quantity', 0))):
                    changes.append({'field': f'Cantidad Comprada de {prod_name}', 'from': p_item.get('quantity'), 'to': c_item.get('quantity')})
                
                if str(float(p_item.get('foreign_price', 0))) != str(float(c_item.get('foreign_price', 0))):
                    changes.append({'field': f'Precio Unitario de {prod_name} (Cant. Comprada: {c_item.get("quantity")})', 'from': p_item.get('foreign_price'), 'to': c_item.get('foreign_price')})
                
                p_date = str(p_item.get('expiration_date')) if p_item.get('expiration_date') else 'N/A'
                c_date = str(c_item.get('expiration_date')) if c_item.get('expiration_date') else 'N/A'
                if p_date != c_date:
                    changes.append({'field': f'Fecha de Vencimiento de {prod_name}', 'from': p_date, 'to': c_date})

        edit_logs.append({
            'editor_name': editor.name if editor else 'Usuario Desconocido',
            'timestamp': local_time,
            'reason': reason,
            'changes': changes
        })
    
    return render_template(
        'logistics/purchase_details.html', 
        purchase=purchase, 
        details=details,
        rate_history=rate_history,
        supplier=supplier,
        user=user,
        audit_log=audit_log,
        audit_user=audit_user,
        audit_timestamp_local=audit_timestamp_local,
        edit_logs=edit_logs
    )

@purchase_bp.route('/purchases', methods=['POST'])
@require_roles('admin', 'management', 'manager')
def create_purchase():
    try:
        foto_factura = request.files.get('invoice_photo')
        if not foto_factura or foto_factura.filename == '':
            return jsonify({"error": "Debe adjuntar la foto de la factura."}), 400

        file_bytes = foto_factura.read()
        filename = foto_factura.filename
        url_generada = "En proceso..."

        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        foreign_prices = request.form.getlist('foreign_price[]')
        expiration_dates = request.form.getlist('expiration_date[]')
        
        items = []
        for i in range(len(product_ids)):
            product_id_val = int(product_ids[i]) if product_ids[i] else None
            exp_date_obj = None
            
            if i < len(expiration_dates) and expiration_dates[i].strip():
                try:
                    exp_date_obj = datetime.strptime(expiration_dates[i].strip(), '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            if not exp_date_obj and product_id_val:
                product = db.session.query(Product).get(product_id_val)
                if product and getattr(product, 'product_type_id', None):
                    p_type = db.session.query(ProductType).get(product.product_type_id)
                    if p_type and getattr(p_type, 'shelf_life_days', None):
                        exp_date_obj = (datetime.now() + timedelta(days=p_type.shelf_life_days)).date()

            items.append({
                'product_id': product_id_val,
                'quantity': float(quantities[i]) if quantities[i] else 0.0,
                'foreign_price': float(foreign_prices[i]) if foreign_prices[i] else 0.0,
                'expiration_date': exp_date_obj
            })
        
        data = {
            'supplier_id': request.form.get('supplier_id', type=int),
            'currency': request.form.get('currency'),
            'exchange_rate': request.form.get('exchange_rate', type=float),
            'user_id': current_user.id if current_user.is_authenticated else (request.form.get('user_id', type=int) or 1),
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

    if result.get("success"):
        purchase_id = result.get("purchase_id")
        
        try:
            for item in data['items']:
                if item['expiration_date'] and item['product_id']:
                    detail = db.session.query(PurchaseDetail).filter_by(
                        purchase_id=purchase_id, 
                        product_id=item['product_id']
                    ).first()
                    if detail:
                        detail.expiration_date = item['expiration_date']
            db.session.commit()
        except Exception as e:
            db.session.rollback()

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
            
        app_instance = current_app._get_current_object()
        
        if purchase_id:
            thread = threading.Thread(
                target=bg_upload_invoice,
                args=(app_instance, purchase_id, file_bytes, filename)
            )
            thread.start()

        return jsonify(result), 201
    else:
        return jsonify(result), 500