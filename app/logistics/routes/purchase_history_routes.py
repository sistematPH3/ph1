from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from app.extensions import db
from app.models import Supplier  

# Importación de las capas del Historial
from app.logistics.repositories.purchase_history_repository import PurchaseHistoryRepository
from app.logistics.services.purchase_history_service import PurchaseHistoryService
from app.logistics.requests.purchase_history_request import PurchaseHistoryFilterRequest

# Definición del Blueprint con el prefijo correcto
purchase_history_bp = Blueprint('purchase_history', __name__)
filter_request_validator = PurchaseHistoryFilterRequest()

def get_history_service():
    """Instancia de forma limpia el servicio inyectándole la base de datos 'db'"""
    repository = PurchaseHistoryRepository(db)
    return PurchaseHistoryService(repository)

# 1. VISTA PRINCIPAL DEL HISTORIAL (CON FILTROS OPERATIVOS)
@purchase_history_bp.route('/purchases/history', methods=['GET'], strict_slashes=False)
def index():
    try:
        service = get_history_service()
        
        # 1. Capturar los parámetros enviados por el formulario de la interfaz
        params = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'supplier_id': request.args.get('supplier_id'),
            'status': request.args.get('status')
        }
        
        # 2. Validar y limpiar los datos con el Request (evita caídas por formatos incorrectos)
        # Si los campos están vacíos, el validador los transformará en None automáticamente
        validated_filters = filter_request_validator.load(params)
        
        # 3. Consultar la base de datos usando los filtros limpios
        purchases = service.get_formatted_history(
            start_date=validated_filters.get('start_date'),
            end_date=validated_filters.get('end_date'),
            supplier_id=validated_filters.get('supplier_id'),
            status=validated_filters.get('status')
        )
        
        # Para llenar el select/dropdown de proveedores en la interfaz
        suppliers = Supplier.query.all()
        
        return render_template('logistics/purchase_history.html', purchases=purchases, suppliers=suppliers)
        
    except ValueError as e:
        # Si las fechas están al revés o el ID está mal, atrapa el diccionario de errores
        flash(f"Error en los filtros aplicados: {str(e)}", "warning")
        suppliers = Supplier.query.all()
        return render_template('logistics/purchase_history.html', purchases=[], suppliers=suppliers)
        
    except Exception as e:
        flash(f"Ocurrió un error inesperado al acceder a la base de datos: {str(e)}", "danger")
        return render_template('logistics/purchase_history.html', purchases=[], suppliers=[])

# 2. JSON DE DETALLES DE COMPRA
@purchase_history_bp.route('/purchases/history/<int:purchase_id>/details', methods=['GET'])
def get_details_json(purchase_id):
    try:
        service = get_history_service()
        summary = service.get_purchase_details_summary(purchase_id)
        
        if not summary:
            return jsonify({"error": "La factura de compra no existe."}), 404

        purchase = summary["purchase"]
        details = summary["details"]
        
        details_list = []
        # CORREGIDO: Desempaquetamos el objeto detalle y el alias del SKU mapeado en el repositorio
        for d, product_sku in details:
            details_list.append({
                "id": d.id,
                "product_id": d.product_id,
                "product_sku": product_sku if product_sku else "S/S (Sin SKU)",
                "quantity": float(d.quantity),
                "foreign_price": float(d.foreign_price) if d.foreign_price is not None else 0.0,
                "price_bs": float(d.price_bs) if d.price_bs is not None else 0.0
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

# 3. ANULACIÓN DE COMPRA
@purchase_history_bp.route('/purchases/history/<int:purchase_id>/annul', methods=['POST'])
def annul(purchase_id):
    try:
        service = get_history_service()
        success = service.process_annulment(purchase_id)
        
        if success:
            flash(f"La compra Nro. {purchase_id} ha sido anulada con éxito.", "success")
        else:
            flash("No se pudo realizar la anulación. Verifique que la compra exista.", "error")
            
    except Exception as e:
        flash(f"Error al procesar la comunicación con la base de datos: {str(e)}", "danger")
        
    return redirect(url_for('purchase_history.index'))