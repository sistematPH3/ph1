from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.extensions import db
from app.logistics.services.purchase_history_service import PurchaseHistoryService
from app.logistics.requests.purchase_history_request import PurchaseHistoryFilterRequest
from app.models import Supplier  

# Tu blueprint independiente
purchase_history_bp = Blueprint('purchase_history', __name__)
filter_request_validator = PurchaseHistoryFilterRequest()

# 1. VISTA PRINCIPAL DEL HISTORIAL (Carga total para el JavaScript)
@purchase_history_bp.route('/purchases/history', methods=['GET'], strict_slashes=False)
def index():
   
    purchases = PurchaseHistoryService.get_formatted_history()
    suppliers = Supplier.query.all()
    return render_template('logistics/purchase_history.html', purchases=purchases, suppliers=suppliers)



@purchase_history_bp.route('/purchases/history/<int:purchase_id>/details', methods=['GET'])
def get_details_json(purchase_id):
    
    summary = PurchaseHistoryService.get_purchase_details_summary(purchase_id)
    if not summary:
        return jsonify({"error": "La factura de compra no existe."}), 404

    purchase = summary["purchase"]
    details = summary["details"]
    
    details_list = []
    for d in details:
        details_list.append({
            "id": d.id,
            "product_id": d.product_id,
            "quantity": float(d.quantity),
            "foreign_price": float(d.foreign_price),
            "price_bs": float(d.price_bs)
        })

    return jsonify({
        "purchase_id": purchase.id,
        "total_amount": float(purchase.total_amount),
        "currency": purchase.currency,
        "exchange_rate": float(purchase.exchange_rate),
        "invoice_url": purchase.invoice_url,
        "status": purchase.status,
        "details": details_list
    }), 200



@purchase_history_bp.route('/purchases/history/<int:purchase_id>/annul', methods=['POST'])
def annul(purchase_id):
    success = PurchaseHistoryService.process_annulment(purchase_id)
    if success:
        flash(f"La compra Nro. {purchase_id} ha sido anulada con éxito.", "success")
    else:
        flash("No se pudo realizar la anulación. Verifique que la compra exista.", "error")
        
    return redirect(url_for('purchase_history.index'))