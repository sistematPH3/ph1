from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.extensions import db
from app.models import Supplier  
from app.models.inventory_model import Product

from app.logistics.repositories.purchase_history_repository import PurchaseHistoryRepository
from app.logistics.services.purchase_history_service import PurchaseHistoryService
from app.logistics.requests.purchase_history_request import PurchaseHistoryFilterRequest

# Importamos el decorador dinámico unificado
from app.decorators.roles import require_roles

purchase_history_bp = Blueprint('purchase_history', __name__)
filter_request_validator = PurchaseHistoryFilterRequest()

def get_history_service():
    repository = PurchaseHistoryRepository(db)
    return PurchaseHistoryService(repository)

@purchase_history_bp.route('/purchases/history', methods=['GET'], strict_slashes=False)
@require_roles('admin', 'management', 'manager')
def index():
    try:
        service = get_history_service()
        
        params = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'supplier_id': request.args.get('supplier_id'),
            'status': request.args.get('status')
        }
        
        validated_data = filter_request_validator.load(params)
        
        suppliers = Supplier.query.filter_by(status='Active').order_by(Supplier.name.asc()).all()
        products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
        
        purchases = service.get_formatted_history(
            start_date=validated_data['start_date'],
            end_date=validated_data['end_date'],
            supplier_id=validated_data['supplier_id'],
            status=validated_data['status']
        )
        
        return render_template(
            'logistics/purchase_history.html', 
            purchases=purchases,
            suppliers=suppliers,
            products=products
        )
        
    except ValueError as val_err:
        flash(f"Parámetros de búsqueda inválidos: {str(val_err)}", "warning")
        return redirect(url_for('purchase_history.index'))
    except Exception as e:
        flash(f"Error interno en el sistema: {str(e)}", "error")
        return render_template('logistics/purchase_history.html', purchases=[], suppliers=[], products=[])

@purchase_history_bp.route('/purchases/history/<int:purchase_id>/details', methods=['GET'])
@require_roles('admin', 'management', 'manager')
def get_details(purchase_id):
    try:
        service = get_history_service()
        data = service.get_purchase_details_summary(purchase_id)
        
        if not data:
            return jsonify({"error": "Compra no encontrada"}), 404
            
        purchase = data['purchase']
        details = data['details']
        
        details_list = []
        for d, product_sku, requires_manual_date in details:
            details_list.append({
                "id": d.id,
                "product_sku": product_sku if product_sku else "(Sin SKU)",
                "quantity": float(d.quantity),
                "foreign_price": float(d.foreign_price) if d.foreign_price is not None else 0.0,
                "price_bs": float(d.price_bs) if d.price_bs is not None else 0.0,
                "expiration_date": d.expiration_date.strftime('%Y-%m-%d') if getattr(d, 'expiration_date', None) else "",
                "requires_manual_date": bool(requires_manual_date)
            })

        return jsonify({
            "purchase_id": purchase.id,
            "total_amount": float(purchase.total_amount) if purchase.total_amount is not None else 0.0,
            "currency": purchase.currency,
            "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate is not None else 0.0,
            "invoice_url": purchase.invoice_url,
            "status": purchase.status,
            "details": details_list
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Error interno en el servidor: {str(e)}"}), 500

@purchase_history_bp.route('/purchases/history/<int:purchase_id>/annul', methods=['POST'])
@require_roles('admin', 'management', 'manager')
def annul(purchase_id):
    try:
        service = get_history_service()
        user_id = 1 
        success = service.process_annulment(purchase_id, user_id)
        
        if success:
            flash(f"La compra Nro. {purchase_id} ha sido anulada con éxito.", "success")
        else:
            flash("No se pudo realizar la anulación. Verifique que la compra exista.", "error")
            
    except Exception as e:
        flash(f"Ocurrió un error crítico durante la anulación: {str(e)}", "error")
        
    return redirect(url_for('purchase_history.index'))

@purchase_history_bp.route('/purchases/history/<int:purchase_id>/edit', methods=['POST'])
@require_roles('admin', 'management', 'manager')
def edit_purchase(purchase_id):
    try:
        service = get_history_service()
        user_id = 1 
        
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Datos incompletos para la edición."}), 400
            
        reason = data.get('reason')
        if not reason or len(reason.strip()) < 5:
            return jsonify({"success": False, "error": "Debe proporcionar un motivo válido para justificar la edición."}), 400
            
        success = service.process_edit(purchase_id, user_id, data['items'], reason.strip())
        
        if success:
            flash(f"La compra Nro. {purchase_id} ha sido modificada con éxito.", "success")
            return jsonify({"success": True}), 200
        else:
            return jsonify({"success": False, "error": "No se pudo editar la compra."}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500