from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import current_user
from sqlalchemy import func
from decimal import ROUND_HALF_UP, Decimal
from datetime import datetime
from io import BytesIO
from flask import send_file
from app.extensions import db
from app.models import Supplier  
from app.models.inventory_model import Product
from app.logistics.repositories.purchase_management_repository import PurchaseManagementRepository
from app.logistics.services.purchase_management_service import PurchaseManagementService
from app.logistics.requests.purchase_management_request import PurchaseManagementFilterRequest
from app.logistics.requests.purchase_validators import PurchaseValidator, es_moneda_bs
from app.decorators.roles import require_roles, require_roles_api

purchase_management_bp = Blueprint('purchase_management', __name__)
filter_request_validator = PurchaseManagementFilterRequest()

def get_management_service():
    repository = PurchaseManagementRepository(db)
    return PurchaseManagementService(repository)

ACTIVE_SUPPLIER_STATUSES = ('ACTIVE', 'ACTIVO', 'OPERATIVO', 'OPERATIVA')


def _flatten_errors(err):
    """Convierte el dict de errores del validador en un texto legible.

    Antes se hacía flash(str(err)) y el usuario veía el dict de Python crudo.
    """
    if isinstance(err, dict):
        partes = []
        for campo, mensajes in err.items():
            if isinstance(mensajes, (list, tuple)):
                texto = ' '.join(str(m) for m in mensajes)
            else:
                texto = str(mensajes)
            partes.append(f"{campo}: {texto}")
        return ' | '.join(partes)
    return str(err)


def _read_filters():
    """Lee y valida los filtros de pantalla compartidos por listado y exportación."""
    return filter_request_validator.load({
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'supplier_id': request.args.get('supplier_id'),
        'status': request.args.get('status')
    })


@purchase_management_bp.route('/purchases/management', methods=['GET'], strict_slashes=False)
@require_roles('admin')
def index():
    try:
        service = get_management_service()
        
        validated_data = _read_filters()
        
        suppliers = Supplier.query.filter(
            func.upper(Supplier.status).in_(ACTIVE_SUPPLIER_STATUSES)
        ).order_by(Supplier.name.asc()).all()
        products = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
        
        purchases = service.get_formatted_history(
            current_user=current_user,
            start_date=validated_data['start_date'],
            end_date=validated_data['end_date'],
            supplier_id=validated_data['supplier_id'],
            status=validated_data['status']
        )
        
        return render_template(
            'logistics/purchase_management.html', 
            purchases=purchases,
            suppliers=suppliers,
            products=products
        )
        
    except ValueError as val_err:
        flash(f"Parámetros de búsqueda inválidos: {_flatten_errors(val_err)}", "warning")
        return redirect(url_for('purchase_management.index'))
    except Exception as e:
        # Sin rollback la sesión queda envenenada y el resto de la request falla.
        db.session.rollback()
        flash(f"Error interno en el sistema: {str(e)}", "error")
        return render_template('logistics/purchase_management.html', purchases=[], suppliers=[], products=[])

@purchase_management_bp.route('/purchases/management/export', methods=['GET'])
@require_roles('admin')
def exportar_listado():
    try:
        from app.reports.services import audit_export_service
        from app.reports.services.audit_export_generators import (
            generar_excel_auditoria, generar_pdf_auditoria)

        formato = request.args.get('formato', 'pdf')
        if formato not in ('pdf', 'excel'):
            return "Formato inválido.", 400

        # Los filtros de fecha y estado se reenvían al export: antes solo se
        # aplicaban q/supplier/date, así que el PDF ignoraba el rango y el estado
        # que el usuario tenía aplicados en pantalla.
        try:
            validados = _read_filters()
        except ValueError as val_err:
            flash(f"Parámetros de exportación inválidos: {_flatten_errors(val_err)}", "warning")
            return redirect(url_for('purchase_management.index'))

        filtros = {
            'formato': formato,
            'q': request.args.get('q', ''),
            'supplier': request.args.get('supplier', ''),
            'date': request.args.get('date', ''),
            'start_date': request.args.get('start_date', ''),
            'end_date': request.args.get('end_date', ''),
            'status': request.args.get('status', ''),
            'supplier_id': (str(validados['supplier_id'])
                            if validados['supplier_id'] else ''),
        }
        documento = audit_export_service.construir_listado_compras(current_user, filtros)

        buffer = BytesIO()
        painter = generar_pdf_auditoria if formato == 'pdf' else generar_excel_auditoria
        archivo = painter(documento['header'], documento['detalle_tablas'])
        buffer.write(archivo.getvalue())
        buffer.seek(0)

        ext = 'pdf' if formato == 'pdf' else 'xlsx'
        mimetype = ('application/pdf' if formato == 'pdf'
                    else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        nombre = f"listado-compras-{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

        # PDF en linea (visor) para evitar gestores externos como IDM.
        return send_file(buffer, as_attachment=(formato != 'pdf'),
                         download_name=nombre, mimetype=mimetype)
    except Exception as e:
        db.session.rollback()
        flash(f"Error generando la exportación: {str(e)}", "error")
        return redirect(url_for('purchase_management.index'))

# Los tres endpoints siguientes responden JSON: usan require_roles_api para
# devolver 401/403 en vez de un 302 al login, que el fetch() del front no sabe
# interpretar (res.json() reventaba y se veía "fallo de conexión").
@purchase_management_bp.route('/purchases/management/<int:purchase_id>/details', methods=['GET'])
@require_roles_api('admin')
def get_details(purchase_id):
    try:
        service = get_management_service()
        data = service.get_purchase_details_summary(purchase_id, current_user=current_user)
        
        if not data:
            return jsonify({"error": "Compra no encontrada"}), 404
            
        purchase = data['purchase']
        details = data['details']
        es_bs = es_moneda_bs(purchase.currency)
        rate = Decimal(str(purchase.exchange_rate)) if purchase.exchange_rate is not None else None
        
        details_list = []
        for row in details:
            d, product_sku, requires_manual_date = row[0], row[1], row[2]
            
            price = Decimal(str(d.foreign_price)) if d.foreign_price is not None else Decimal('0.00')
            qty = Decimal(str(d.quantity))
            # price_bs ya es el precio UNITARIO en Bs: el subtotal no se
            # multiplica otra vez por la tasa (en Bs tampoco, antes sí).
            if d.price_bs is not None:
                unitario_bs = Decimal(str(d.price_bs))
            elif es_bs:
                unitario_bs = price
            elif rate is not None:
                unitario_bs = price * rate
            else:
                # Sin tasa el monto en Bs es desconocido; se devuelve None para
                # que el modal muestre "—" y no 0,00 (que parecía compra gratis).
                unitario_bs = None
            subtotal_bs = (None if unitario_bs is None else (
                qty * unitario_bs).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP))

            details_list.append({
                "id": d.id,
                "product_sku": product_sku if product_sku else "(Sin SKU)",
                "quantity": float(d.quantity),
                "foreign_price": float(price),
                "subtotal_bs": float(subtotal_bs) if subtotal_bs is not None else None,
                "price_bs": float(d.price_bs) if d.price_bs is not None else None,
                "expiration_date": d.expiration_date.strftime('%Y-%m-%d') if d.expiration_date else "",
                "lot_number": d.lot_number if d.lot_number else "N/A",
                "requires_manual_date": bool(requires_manual_date)
            })

        return jsonify({
            "purchase_id": purchase.id,
            "total_amount": float(purchase.total_amount) if purchase.total_amount is not None else None,
            "currency": purchase.currency,
            "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate is not None else None,
            "invoice_url": purchase.invoice_url,
            "status": purchase.status,
            "details": details_list,
            "can_modify": data.get('can_modify', False),
            "remaining_seconds": data.get('remaining_seconds', 0),
            "time_limits": data.get('time_limits', {'admin_days': 7, 'other_hours': 24})
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error interno en el servidor: {str(e)}"}), 500

@purchase_management_bp.route('/purchases/management/<int:purchase_id>/annul', methods=['POST'])
@require_roles_api('admin')
def annul(purchase_id):
    try:
        service = get_management_service()
        success = service.process_annulment(purchase_id, current_user)
        
        if success:
            return jsonify({"success": True, "message": f"La compra Nro. {purchase_id} ha sido anulada con éxito."}), 200
        else:
            return jsonify({"success": False, "error": "La compra no se pudo anular. Verifique que exista y esté en estado COMPLETADA."}), 400
            
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ocurrió un error crítico durante la anulación: {str(e)}"}), 500

@purchase_management_bp.route('/purchases/management/<int:purchase_id>/edit', methods=['POST'])
@require_roles_api('admin')
def edit_purchase(purchase_id):
    try:
        service = get_management_service()
        
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or 'items' not in data:
            return jsonify({"success": False, "error": "Datos incompletos para la edición."}), 400
            
        items = data['items']
        if not isinstance(items, list) or len(items) == 0:
            return jsonify({"success": False, "error": "Debe incluir al menos un insumo para la edición."}), 400
        
        # Antes: data.get('reason') y luego len(reason.strip()) reventaba con
        # AttributeError (500) si el motivo no era un string.
        reason_error = PurchaseValidator.validate_edit_reason(data.get('reason'))
        if reason_error:
            return jsonify({"success": False, "error": reason_error}), 400
        reason = data['reason'].strip()

        item_errors = PurchaseValidator.validate_edit_items(items)
        if item_errors:
            return jsonify({"success": False, "error": "Datos inválidos", "details": item_errors}), 400

        success = service.process_edit(purchase_id, current_user, items, reason)
        
        if success:
            return jsonify({"success": True, "message": f"La compra Nro. {purchase_id} ha sido modificada con éxito."}), 200
        else:
            return jsonify({"success": False, "error": "La compra no se pudo editar. Verifique que exista y esté en estado COMPLETADA."}), 400
            
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500