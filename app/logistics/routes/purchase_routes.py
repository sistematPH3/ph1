import os
import threading
import io
from flask import Blueprint, request, jsonify, render_template, current_app, flash, redirect, url_for, send_file
from flask_login import current_user
from sqlalchemy import func
from datetime import datetime, timedelta
import pytz
from werkzeug.utils import secure_filename
from app.integrations.ocr.ocr_services import (
    leer_texto,
    limpiar_para_evaluar,
)
from app.logistics.requests.purchase_validators import (
    PurchaseValidator,
    evaluar_comprobante,
    normalizar_numero,
    normalizar_moneda,
)
from app.logistics.services.purchase_service import PurchaseService
from app import db 
from app.models import ProductType, Inventory
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
            # Antes se hacia rollback y ya: la excepcion se perdia y la compra
            # se quedaba con invoice_url = "En proceso..." para siempre, sin
            # que nadie supiera por que.
            app_instance.logger.error(
                "No se pudo subir la foto de la factura de la compra %s a ImgBB: %s",
                purchase_id, e, exc_info=True,
            )

@purchase_bp.route('/purchases/new', methods=['GET'])
@require_roles('admin')
def new_purchase_form():
    products_query = db.session.query(Product, ProductType).outerjoin(
        ProductType, Product.product_type_id == ProductType.id
    ).filter(Product.is_active == True).order_by(Product.name.asc()).all()
    
    products = []
    for prod, ptype in products_query:
        products.append({
            'id': prod.id,
            'name': prod.name,
            'sku': prod.sku,
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
@require_roles('admin')
def view_purchase_details(purchase_id):
    purchase = Purchase.query.get_or_404(purchase_id)
    supplier = Supplier.query.get(purchase.supplier_id)
    user = User.query.get(purchase.user_id)
    
    if current_user.role and current_user.role.name.lower() == 'finance':
        user_location_id = getattr(current_user, 'location_id', None)
        purchase_location_id = getattr(user, 'location_id', None) if user else None
        
        if purchase_location_id and user_location_id and purchase_location_id != user_location_id:
            flash('No tienes autorización para consultar compras de otra sede.', 'danger')
            return redirect(url_for('audit_purchase.list_purchase_audits'))
    
    details = db.session.query(PurchaseDetail, Product.name, Product.sku)\
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
                changes.append({'field': f'Insumo Añadido: {prod_name}', 'from': '-', 'to': f"Cant. Comprada: {c_item.get('quantity')} | Lote: {c_item.get('lot_number')} | Precio Unitario: {c_item.get('foreign_price')}"})
            elif p_item and not c_item:
                changes.append({'field': f'Insumo Eliminado: {prod_name}', 'from': f"Cant. Comprada: {p_item.get('quantity')} | Lote: {p_item.get('lot_number')} | Precio Unitario: {p_item.get('foreign_price')}", 'to': '-'})
            else:
                if str(float(p_item.get('quantity', 0))) != str(float(c_item.get('quantity', 0))):
                    changes.append({'field': f'Cantidad Comprada de {prod_name}', 'from': p_item.get('quantity'), 'to': c_item.get('quantity')})
                
                if str(float(p_item.get('foreign_price', 0))) != str(float(c_item.get('foreign_price', 0))):
                    changes.append({'field': f'Precio Unitario de {prod_name} (Cant. Comprada: {c_item.get("quantity")})', 'from': p_item.get('foreign_price'), 'to': c_item.get('foreign_price')})
                
                p_date = str(p_item.get('expiration_date')) if p_item.get('expiration_date') else 'N/A'
                c_date = str(c_item.get('expiration_date')) if c_item.get('expiration_date') else 'N/A'
                if p_date != c_date:
                    changes.append({'field': f'Fecha de Vencimiento de {prod_name}', 'from': p_date, 'to': c_date})
                
                p_lot = str(p_item.get('lot_number')) if p_item.get('lot_number') else 'N/A'
                c_lot = str(c_item.get('lot_number')) if c_item.get('lot_number') else 'N/A'
                if p_lot != c_lot:
                    changes.append({'field': f'Número de Lote de {prod_name}', 'from': p_lot, 'to': c_lot})

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

@purchase_bp.route('/purchases/<int:purchase_id>/export', methods=['GET'])
@require_roles('admin')
def export_purchase_detail(purchase_id):
    if not Purchase.query.get(purchase_id):
        flash('La compra solicitada no existe.', 'error')
        return redirect(url_for('purchase_routes.view_purchase_details',
                                purchase_id=purchase_id))

    formato = request.args.get('formato', 'pdf')
    if formato not in ('pdf', 'excel'):
        return 'Formato inválido.', 400

    from app.reports.services import audit_export_service
    from app.reports.services.audit_export_generators import (
        generar_excel_auditoria, generar_pdf_auditoria)

    documento = audit_export_service.construir_detalle_compra(
        current_user, purchase_id, {'formato': formato})
    if documento.get('error'):
        flash(documento['error'], 'error')
        return redirect(url_for('purchase_routes.view_purchase_details',
                                purchase_id=purchase_id))

    painter = (generar_pdf_auditoria if formato == 'pdf'
               else generar_excel_auditoria)
    buffer = painter(documento['header'], documento['detalle_tablas'])
    buffer.seek(0)

    ext = 'pdf' if formato == 'pdf' else 'xlsx'
    mimetype = ('application/pdf' if formato == 'pdf'
                else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    nombre = (f"detalle-compra-{purchase_id}-"
              f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}")
    # PDF en linea (visor) para evitar gestores externos como IDM.
    return send_file(buffer, as_attachment=(formato != 'pdf'),
                     download_name=nombre, mimetype=mimetype)


def _validar_comprobante(file_bytes):
    """
    Lee la foto y decide que tipo de comprobante es.

    Si el OCR no esta disponible NO se marca la foto como aceptada. Antes se
    devolvia 'puede_aceptar': True para que la compra no se cayera si faltaba
    la libreria, pero eso hacia justo lo contrario de lo que se pidio: la puerta
    se abria para CUALQUIER imagen en cuanto el motor fallaba, y la compra
    quedaba guardada sin verificar. Ahora el veredicto es 'sin_lectura' con
    'puede_aceptar': False y la compra se detiene, sin excepciones por modo.
    """
    umbral = current_app.config.get('INVOICE_UMBRAL_ACEPTACION', 60)

    lineas, error = leer_texto(file_bytes)
    if error:
        current_app.logger.error(
            "OCR no disponible, la foto NO se puede verificar: %s", error)
        return {
            'veredicto': 'sin_lectura', 'tipo': 'desconocido', 'puntaje': 0,
            'marcas': [], 'puede_aceptar': False,
            'sin_lectura': True,
            'detalle': f'No se pudo leer la foto: {error}',
        }

    evaluacion = evaluar_comprobante(limpiar_para_evaluar(lineas), umbral=umbral)
    evaluacion['texto'] = ' | '.join(str(linea) for linea in lineas)
    return evaluacion


def _mensaje_factura(validacion):
    """
    Texto de exito del boton, cuando la foto SI fue aceptada.

    Solo se llega aqui si la puerta de arriba dejo pasar la foto, asi que este
    texto solo confirma. Los textos de rechazo (y el unico caso en que la
    compra NO se registro) salen de _mensaje_rechazo_factura().
    """
    if validacion.get('tipo') == 'comprobante_tarjeta':
        return 'Comprobante de tarjeta verificado.'
    return 'Factura verificada.'


def _mensaje_rechazo_factura(validacion):
    """
    Texto cuando la compra NO se registro por culpa de la foto (modo 'strict').

    No se puede reutilizar _mensaje_factura: ese dice "la compra se registro,
    pero..." y aqui no hay ninguna compra registrada. El mensaje va en futuro
    porque todavia se puede rehacer la foto y reenviar el formulario sin
    perder nada de lo que el usuario ya escribio.
    """
    if validacion.get('veredicto') == 'sin_lectura':
        return (
            'La compra no se registró: el sistema no pudo leer la foto porque '
            'el lector de texto no está disponible. Avísale a quien administra '
            'el sistema; no reintentes la foto, no es un problema de la imagen.'
        )

    if validacion.get('veredicto') == 'ilegible':
        return (
            'La compra no se registró: no se pudo leer el texto de la foto. '
            'Vuelve a tomarla con más luz, de frente y sin que quede cortada.'
        )


    return (
        'La compra no se registró: la foto no parece una factura ni un '
        'comprobante de compra. Revisa que hayas fotografiado el comprobante '
        'completo, con el emisor, el RIF y los importes legibles.'
    )


def _mensaje_rechazo_preview(validacion):
    """
    Texto para cuando la foto se revisa AL MONTARLA, todavia sin registrar.

    No puede reutilizarse _mensaje_rechazo_factura: ese dice "la compra no se
    registro", y aqui todavia no se le dio registrar. Al usuario le llegaria un
    texto hablando de algo que no ha pasado, cuando lo unico queoccurrido es
    que la foto no sirvio.
    """
    if validacion.get('veredicto') == 'sin_lectura':
        return (
            'No se pudo leer la foto: el lector de texto del sistema no está '
            'disponible. Avísale a quien administra; la foto puede estar bien.'
        )

    if validacion.get('veredicto') == 'ilegible':
        return (
            'No se pudo leer el texto de la foto. Vuelve a tomarla con más luz, '
            'de frente y sin que quede cortada.'
        )

    return (
        'La foto no parece una factura ni un comprobante de compra. Revisa que '
        'hayas fotografiado el comprobante completo, con el emisor, el RIF y los '
        'importes legibles.'
    )


def _registrar_veredicto(purchase_id, validacion):
    """
    Deja el veredicto en la tabla de auditoria de compras, que ya existe.

    Se reutiliza PurchaseAuditLog en vez de crear columnas nuevas: guardar el
    puntaje aqui permite medir con datos reales antes de decidir si un puntaje
    bajo debe bloquear la compra.
    """
    try:
        texto = (validacion.get('texto') or '')[:600]
        db.session.add(PurchaseAuditLog(
            purchase_id=purchase_id,
            action_type='INVOICE_VERDICT',
            previous_data={},
            new_data={
                'veredicto': validacion.get('veredicto'),
                'tipo': validacion.get('tipo'),
                'puntaje': validacion.get('puntaje'),
                'marcas': validacion.get('marcas'),
                'detalle': validacion.get('detalle'),
                'texto_ocr': texto,
                'modo': current_app.config.get('INVOICE_VALIDATION_MODE', 'strict'),
            },
            user_id=current_user.id,
        ))
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.warning(
            "No se pudo registrar el veredicto de la foto de la compra %s: %s",
            purchase_id, error,
        )


@purchase_bp.route('/purchases/validar-foto', methods=['POST'])
@require_roles('admin')
def validar_foto_comprobante():
    """
    Revisa la foto en cuanto el usuario la monta, sin registrar nada.

    Antes la unica validacion vivia dentro de POST /purchases: la foto no se
    miraba hasta que se le daba "registrar", y el formulario ya mostraba un
    check verde al montarla, como si estuviera aprobada. Este endpoint solo
    LEE la imagen y devuelve el veredicto: no crea compra, no descuenta stock
    y no escribe en la base de datos.

    El submit vuelve a validar la misma foto en el servidor. Este endpoint es
    para avisar temprano, no para decidir: lo que responde el navegador no se
    toma como cierto.
    """
    try:
        foto = request.files.get('invoice_photo')
        es_valida, error_imagen, info_imagen = PurchaseValidator.validate_invoice_image(foto)
        if not es_valida:
            return jsonify({
                "puede_aceptar": False,
                "veredicto": "imagen_invalida",
                "error": error_imagen,
                "campo": "invoice_photo",
            }), 400

        validacion = _validar_comprobante(info_imagen['bytes'])
        modo = current_app.config.get('INVOICE_VALIDATION_MODE', 'strict')
        umbral = current_app.config.get('INVOICE_UMBRAL_ACEPTACION', 60)

        # Sin excepciones: lo que el OCR decidio es lo que se le dice al
        # usuario. Antes se hacia 'puede_aceptar or modo != strict', de modo
        # que en 'warn' el navegador pintaba la foto en verde aunque el OCR la
        # hubiera rechazado, y el usuario se enteraba del problema solo al
        # darle registrar, cuando ya habia escrito todo el formulario.
        return jsonify({
            "puede_aceptar": bool(validacion['puede_aceptar']),
            "veredicto": validacion['veredicto'],
            "tipo": validacion.get('tipo'),
            "puntaje": validacion.get('puntaje'),
            "umbral": umbral,
            "modo": modo,
            "diagnostico": validacion.get('detalle'),
            "mensaje": _mensaje_rechazo_preview(validacion)
                       if not validacion['puede_aceptar'] else None,
        }), 200
    except Exception as error:
        current_app.logger.error(
            "No se pudo validar la foto del comprobante: %s", error, exc_info=True,
        )
        return jsonify({
            "puede_aceptar": False,
            "veredicto": "error",
            "error": "No se pudo revisar la foto. Vuelve a tomarla.",
        }), 500


@purchase_bp.route('/purchases', methods=['POST'])
@require_roles('admin')
def create_purchase():
    try:
        foto_factura = request.files.get('invoice_photo')

        # Antes solo se miraba que el campo viniera informado y acto seguido se
        # hacia .read() sin ningun limite: cualquier admin podia adjuntar un
        # archivo de 2 GB (que se iba entero a la memoria) o un .exe disfrazado
        # de .jpg. Ahora se comprueba el archivo de verdad.
        es_valida, error_imagen, info_imagen = PurchaseValidator.validate_invoice_image(foto_factura)
        if not es_valida:
            return jsonify({"error": error_imagen, "campo": "invoice_photo"}), 400

        file_bytes = info_imagen['bytes']

        # El nombre lo manda el cliente: se limpia y se le fuerza la extension
        # que el archivo REAL tiene, no la que el dice la extension enviada.
        nombre_seguro = secure_filename(foto_factura.filename or '')
        nombre_seguro = f"{os.path.splitext(nombre_seguro)[0] or 'factura'}{info_imagen['extension']}"
        url_generada = "En proceso..."

        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        lot_numbers = request.form.getlist('lot_number[]')
        foreign_prices = request.form.getlist('foreign_price[]')
        expiration_dates = request.form.getlist('expiration_date[]')
        
        items = []
        date_errors = []

        # Las listas del formulario van en paralelo (producto, cantidad, lote,
        # precio, fecha). Antes solo lote y fecha comprobaban el indice: si
        # faltaba una cantidad o un precio, quantities[i] reventaba con
        # IndexError y la respuesta era un 400 con el texto crudo de Python
        # ("list index out of range") en vez de un mensaje util.
        for etiqueta, valores in (('cantidad', quantities),
                                  ('precio', foreign_prices),
                                  ('lote', lot_numbers),
                                  ('fecha', expiration_dates)):
            if len(valores) < len(product_ids):
                return jsonify({
                    "error": "El formulario está incompleto.",
                    "details": (
                        f'Faltan {len(product_ids) - len(valores)} {etiqueta}(s) '
                        f'para {len(product_ids)} producto(s). Recarga la '
                        f'pantalla y revisa las líneas antes de guardar.'
                    ),
                    "campo": etiqueta,
                }), 400

        for i in range(len(product_ids)):
            product_id_val = int(product_ids[i]) if product_ids[i] else None
            exp_date_obj = None
            
            if i < len(expiration_dates) and expiration_dates[i].strip():
                try:
                    exp_date_obj = datetime.strptime(expiration_dates[i].strip(), '%Y-%m-%d').date()
                except ValueError:
                    date_errors.append(f"fila {i + 1}: fecha de vencimiento inválida '{expiration_dates[i].strip()}' (formato esperado AAAA-MM-DD)")
            
            if not exp_date_obj and product_id_val:
                product = db.session.query(Product).get(product_id_val)
                if product and getattr(product, 'product_type_id', None):
                    p_type = db.session.query(ProductType).get(product.product_type_id)
                    if p_type and getattr(p_type, 'shelf_life_days', None):
                        exp_date_obj = (datetime.now() + timedelta(days=p_type.shelf_life_days)).date()

            lot_val = lot_numbers[i].strip() if i < len(lot_numbers) and lot_numbers[i] else None
            if lot_val and len(lot_val) > 50:
                lot_val = lot_val[:50]

            items.append({
                'product_id': product_id_val,
                # Se conserva el TEXTO del campo. Convertirlo aqui con float()
                # rompia la convencion venezolana antes de que el servicio la
                # aplicara: float("1.500") es 1.5, no 1500.
                'quantity': quantities[i] if quantities[i] else 0.0,
                'foreign_price': foreign_prices[i] if foreign_prices[i] else 0.0,
                'expiration_date': exp_date_obj,
                'lot_number': lot_val
            })

        if date_errors:
            return jsonify({"error": "Error al procesar los campos del formulario.", "details": {"expiration_date": date_errors}}), 400
        
        data = {
            'supplier_id': request.form.get('supplier_id', type=int),
            'currency': request.form.get('currency'),
            # Texto crudo, no type=float: la convencion de miles se aplica una
            # sola vez, en normalizar_numero().
            'exchange_rate': request.form.get('exchange_rate'),
            'user_id': current_user.id if current_user.is_authenticated else (request.form.get('user_id', type=int) or 1),
            'invoice_url': url_generada,
            'items': items
        }
    except Exception:
        # Antes se devolvia str(e). Con excepciones de SQLAlchemy eso incluye
        # la sentencia completa y sus parametros, y con IndexError el texto
        # crudo de Python. El detalle se queda en el log del servidor.
        current_app.logger.exception(
            "Error al procesar los campos del formulario de compra")
        return jsonify({
            "error": "Error al procesar los campos del formulario.",
            "details": "Revisa las líneas del formulario e inténtalo de nuevo.",
        }), 400

    if not data:
        return jsonify({"error": "No se recibieron datos en la petición."}), 400

    # Invocación directa a PurchaseValidator
    is_valid, errors = PurchaseValidator.validate_create(data)
    if not is_valid:
        return jsonify({"error": "Datos inválidos", "details": errors}), 400

    # Valida que el proveedor y los productos existan y estén activos.
    supplier = Supplier.query.get(data['supplier_id'])
    if not supplier or str(supplier.status or '').upper() not in ('ACTIVE', 'ACTIVO', 'OPERATIVO', 'OPERATIVA'):
        return jsonify({"error": "Datos inválidos", "details": {"supplier_id": "El proveedor no existe o no está activo."}}), 400

    missing_products = []
    for item in items:
        prod = db.session.query(Product).get(item['product_id'])
        if not prod or not prod.is_active:
            missing_products.append(item['product_id'])
    if missing_products:
        return jsonify({"error": "Datos inválidos", "details": {"product_id": f"Los siguientes productos no existen o están inactivos: {missing_products}"}}), 400

    # --- La foto tiene que parecer un comprobante -----------------------------
    # Va ANTES de registrar la compra: si se rechazara despues, el stock ya se
    # habria descontado y habria que revertirlo.
    validacion_factura = _validar_comprobante(file_bytes)
    modo = current_app.config.get('INVOICE_VALIDATION_MODE', 'strict')
    umbral = current_app.config.get('INVOICE_UMBRAL_ACEPTACION', 60)

    # La foto de la factura es OBLIGATORIA, sin modo que la dispense. Si el OCR
    # no confirma que sea un comprobante de compra, la compra no se registra:
    # no hay compra, no hay stock, no hay auditoria. El usuario solo puede
    # seguir tomando la foto y reenviar el formulario.
    #
    # Antes este bloque solo rechazaba en modo 'strict' y en 'warn' dejaba
    # pasar igual, con un simple warning al log. Eso hacia que el sistema
    # aceptara imagenes que no eran facturas, que es justo lo que no debe
    # pasar: el modo queda como referencia de lo que se evaluo, no como
    # interruptor para saltarse la evidencia.
    if not validacion_factura['puede_aceptar']:
        # El mensaje tiene que decirle QUE hacer, no solo que fallo: en este
        # punto la compra NO se creo, asi que el usuario puede rehacer la
        # foto y reenviar el formulario sin perder nada de lo que escribio.
        #
        # Si lo que fallo fue el motor y no la foto, el titular no puede
        # decir "no se pudo confirmar que la foto sea un comprobante":
        # esa foto puede estar perfecta y le estaria mandando a repetir
        # una captura que nunca va a funcionar.
        sin_lectura = validacion_factura.get('veredicto') == 'sin_lectura'
        current_app.logger.warning(
            "Compra DETENIDA: la foto no es un comprobante de compra "
            "(veredicto=%s, puntaje=%s). No se registro nada.",
            validacion_factura.get('veredicto'),
            validacion_factura.get('puntaje'),
        )
        return jsonify({
            "error": (
                "El sistema no pudo leer la foto."
                if sin_lectura else
                "No se pudo confirmar que la foto sea un comprobante."
            ),
            "details": _mensaje_rechazo_factura(validacion_factura),
            "campo": "invoice_photo",
            "motivo": validacion_factura['veredicto'],
            "diagnostico": validacion_factura['detalle'],
        }), 400

    result = PurchaseService.register_purchase(data)

    if result.get("success"):
        purchase_id = result.get("purchase_id")

        _registrar_veredicto(purchase_id, validacion_factura)

        try:
            # normalizar_moneda y no la limpieza propia: una compra en 'BS,S'
            # es en bolivares, y con la comparacion contra ('VES','BS') la tasa
            # de ese BS se archivaba como si fuera la de una moneda extranjera.
            moneda_historial = normalizar_moneda(data['currency'])
            # La tasa registrada de una compra en Bs es la referencia BCV (Bs por $);
            # no tiene sentido archivarla como tasa de la propia moneda Bs.
            if moneda_historial not in ('BS',):
                # data['exchange_rate'] es el TEXTO que escribio el usuario
                # ("36,50"). La columna es Numeric(15,4): mandarle la cadena
                # cruda hacia que PostgreSQL la rechazara, la compra ya
                # estaba guardada, el rollback se comia el fallo y la serie de
                # tasas se perdia en silencio, sin un solo log.
                historial_tasa = ExchangeRateHistory(
                    currency=moneda_historial,
                    rate=normalizar_numero(data['exchange_rate']),
                    source='COMPRA REGISTRADA',
                    timestamp=datetime.now(),
                    user_id=data['user_id']
                )
                db.session.add(historial_tasa)
                db.session.commit()
        except Exception:
            db.session.rollback()
            # La compra YA esta guardada: esto solo es el archivo de la tasa.
            # Antes la excepcion se guardaba en 'e' y no se usaba para nada,
            # asi que nadie se enteraba de que la serie se estaba perdiendo.
            current_app.logger.exception(
                "No se pudo archivar la tasa aplicada en la compra %s. "
                "La compra SI quedo registrada.", purchase_id)
            
        app_instance = current_app._get_current_object()
        
        if purchase_id:
            thread = threading.Thread(
                target=bg_upload_invoice,
                args=(app_instance, purchase_id, file_bytes, nombre_seguro)
            )
            thread.start()

        return jsonify({
            **result,
            # El veredicto viaja en la respuesta para que la pantalla pueda
            # avisar al usuario. Sin esto el usuario solo ve "compra registrada"
            # y nunca se entera de que la foto no era una factura.
            'factura': {
                'veredicto': validacion_factura.get('veredicto'),
                'tipo': validacion_factura.get('tipo'),
                'puntaje': validacion_factura.get('puntaje'),
                'aceptada': bool(validacion_factura.get('puede_aceptar')),
                'mensaje': _mensaje_factura(validacion_factura),
            },
        }), 201
    else:
        return jsonify(result), 500