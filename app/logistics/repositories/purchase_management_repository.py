from app.models import Purchase, PurchaseDetail, Supplier, PurchaseAuditLog, Product, ProductType, Inventory, AppParameter, ExchangeRateHistory
from decimal import ROUND_HALF_UP, Decimal
from datetime import UTC, datetime, timedelta
from sqlalchemy import text
import json
from app.logistics.requests.purchase_validators import (es_moneda_bs,
                                                        normalizar_moneda,
                                                        parsear_decimal,
                                                        parsear_fecha)
from app.time_utils import current_ve_time

# Las compras impactan siempre el Almacén Central.
ALMACEN_CENTRAL_ID = 1
ALMACEN_CENTRAL_NOMBRE = 'Almacén Central'
CERO = Decimal('0.00')


class PurchaseManagementRepository:
    def __init__(self, db_connection):
        self.db = db_connection
        self._app_params_cache = None

    # ------------------------------------------------------------------
    # Helpers de acceso a datos
    # ------------------------------------------------------------------
    def _get_product(self, product_id):
        return self.db.session.get(Product, product_id)

    def _get_inventory(self, product_id):
        return self.db.session.query(Inventory).filter_by(
            location_id=ALMACEN_CENTRAL_ID,
            product_id=product_id
        ).first()

    @staticmethod
    def _disponible(inventory_record):
        """Stock realmente disponible: físico menos tránsito y mermas pendientes.

        Antes se comparaba contra current_quantity, lo que permitía anular o
        editar compras sobre stock ya comprometido en tránsito o congelado por
        una merma pendiente.
        """
        if inventory_record is None:
            return CERO
        return inventory_record.available_quantity()

    def _severidad(self, product, prev_qty, new_qty):
        """REABASTECIDO solo al cruzar el mínimo configurado del producto.

        Antes comparaba contra un 20 fijo, ignorando el min_stock por producto.
        """
        minimo = product.min_stock_efectivo if product is not None else Decimal('20.00')
        return 'REABASTECIDO' if prev_qty <= minimo < new_qty else 'NORMAL'

    def _get_or_create_inventory(self, product_id, initial_qty):
        """Devuelve (registro, cantidad_previa). Crea el registro si no existe."""
        inventory_record = self._get_inventory(product_id)
        if inventory_record is not None:
            return inventory_record, Decimal(str(inventory_record.current_quantity))
        product = self._get_product(product_id)
        nuevo = Inventory(
            location_id=ALMACEN_CENTRAL_ID,
            product_id=product_id,
            current_quantity=initial_qty,
            min_stock=product.min_stock_efectivo if product is not None else Decimal('20.00'),
            transit_quantity=CERO
        )
        self.db.session.add(nuevo)
        return nuevo, CERO

    # ------------------------------------------------------------------
    # Auditoría de inventario
    # ------------------------------------------------------------------
    def _write_audit(self, user_id, action, severity, product_id, lot_number,
                     prev_qty, new_qty, notes):
        """Escribe un registro en audit_logs (misma tabla que AGREGAR compras)."""
        product = self._get_product(product_id)
        pname = product.name if product else f"ID {product_id}"
        changed = {
            "location_id": ALMACEN_CENTRAL_ID,
            "location_name": ALMACEN_CENTRAL_NOMBRE,
            "product_id": product_id,
            "product_name": pname,
            "lot_number": lot_number,
            "previous_quantity": float(prev_qty),
            "new_quantity": float(new_qty),
            "quantity_changed": float(new_qty - prev_qty),
            "notes": notes,
        }
        self.db.session.execute(text("""
            INSERT INTO audit_logs (user_id, action, severity, location_id, changed_data, timestamp)
            VALUES (:uid, :action, :sev, 1, :cdata, :ts)
        """), {
            'uid': user_id,
            'action': action,
            'sev': severity,
            'cdata': json.dumps(changed),
            # audit_logs.timestamp usa current_ve_time por defecto; se pasa
            # explícitamente para no dejar la fila en la hora local del
            # servidor (4 h menos) frente al resto de flujos que auditan.
            'ts': current_ve_time()
        })

    # ------------------------------------------------------------------
    # Consultas de listado
    # ------------------------------------------------------------------
    def get_filtered_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        # outerjoin: Purchase.supplier_id es nullable y antes el INNER JOIN
        # descartaba del listado toda compra sin proveedor (y del reporte).
        query = self.db.session.query(
            Purchase, Supplier.name.label('supplier_name')
        ).outerjoin(Supplier, Purchase.supplier_id == Supplier.id)

        if start_date:
            query = query.filter(Purchase.purchase_date >= start_date)
        if end_date:
            query = query.filter(Purchase.purchase_date < end_date)

        if supplier_id:
            query = query.filter(Purchase.supplier_id == supplier_id)

        if status:
            query = query.filter(Purchase.status == status)

        return query.order_by(Purchase.purchase_date.desc()).all()

    def get_app_parameters(self):
        """Parámetros configurables de gestión de compras (límites de tiempo, etc.).

        Se memoriza por instancia (el repositorio se crea por request) porque
        can_modify() lo consulta una vez por cada compra del listado y generaba
        un N+1 de consultas.
        """
        if self._app_params_cache is None:
            registros = self.db.session.query(AppParameter).all()
            self._app_params_cache = {p.key: p.value for p in registros}
        return self._app_params_cache

    def _get_current_exchange_rate(self, currency):
        """Tasa vigente para una moneda, o None si no hay registro.

        Solo se usa como respaldo cuando la factura no trae tasa guardada.
        """
        if es_moneda_bs(currency):
            return Decimal('1.0000')
        codigo = normalizar_moneda(currency)
        rate_record = (self.db.session.query(ExchangeRateHistory.rate)
                       .filter(ExchangeRateHistory.currency == codigo)
                       .order_by(ExchangeRateHistory.timestamp.desc())
                       .first())
        if rate_record is not None and rate_record.rate is not None:
            return Decimal(str(rate_record.rate))
        return None

    def _resolve_exchange_rate(self, purchase):
        """Tasa a usar para recalcular los Bs de una compra ya registrada.

        Se conserva la tasa con la que se facturó. Antes se usaba la tasa del día
        al editar, lo que revaluaba facturas ya cerradas y dejaba la auditoría mostrando
        una tasa que no era la aplicada a los renglones.
        """
        if es_moneda_bs(purchase.currency):
            return Decimal('1.0000')
        guardada = purchase.exchange_rate
        if guardada is not None and Decimal(str(guardada)) > CERO:
            return Decimal(str(guardada))
        actual = self._get_current_exchange_rate(purchase.currency)
        if actual is None:
            raise ValueError(
                f"La compra Nro. {purchase.id} no tiene tasa de cambio guardada y no hay "
                f"tasa vigente para {purchase.currency}. Regístrela antes de editar."
            )
        purchase.exchange_rate = actual
        return actual

    def get_purchase_by_id(self, purchase_id):
        return self.db.session.get(Purchase, purchase_id)

    def get_details_by_purchase_id(self, purchase_id):
        return self.db.session.query(
            PurchaseDetail,
            Product.sku.label('product_sku'),
            ProductType.requires_manual_date.label('requires_manual_date')
        ).outerjoin(Product, PurchaseDetail.product_id == Product.id)\
         .outerjoin(ProductType, Product.product_type_id == ProductType.id)\
         .filter(PurchaseDetail.purchase_id == purchase_id).all()

    # ------------------------------------------------------------------
    # Instantáneas para la auditoría de la compra
    # ------------------------------------------------------------------
    @staticmethod
    def _detalle_snapshot(detail):
        return {
            "id": detail.id,
            "product_id": detail.product_id,
            "quantity": float(detail.quantity),
            "foreign_price": float(detail.foreign_price) if detail.foreign_price is not None else 0.0,
            "price_bs": float(detail.price_bs) if detail.price_bs is not None else 0.0,
            "expiration_date": str(detail.expiration_date) if detail.expiration_date else None,
            "lot_number": detail.lot_number if detail.lot_number else None
        }

    def _compra_snapshot(self, purchase, detalles):
        return {
            "id": purchase.id,
            "supplier_id": purchase.supplier_id,
            "total_amount": float(purchase.total_amount) if purchase.total_amount is not None else 0.0,
            "currency": purchase.currency,
            "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate is not None else 0.0,
            "status": purchase.status,
            "details": [self._detalle_snapshot(d) for d in detalles]
        }

    # ------------------------------------------------------------------
    # Anulación lógica
    # ------------------------------------------------------------------
    def logical_annulment(self, purchase_id, user_id):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status != 'COMPLETED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(
                purchase_id=purchase_id).all()

            # Se acumula la salida por producto ANTES de validar. Antes se
            # comparaba renglón contra renglón, así que dos líneas del mismo
            # producto podían pasar el chequeo individual y dejar el stock
            # en negativo al aplicarlas.
            salida_por_producto = {}
            for detail in details:
                salida_por_producto[detail.product_id] = (
                    salida_por_producto.get(detail.product_id, CERO)
                    + Decimal(str(detail.quantity))
                )

            for product_id, cantidad in salida_por_producto.items():
                disponible = self._disponible(self._get_inventory(product_id))
                if disponible < cantidad:
                    product = self._get_product(product_id)
                    prod_name = product.name if product else f"ID {product_id}"
                    raise ValueError(
                        f"No se puede anular. Stock insuficiente de '{prod_name}' en el "
                        f"{ALMACEN_CENTRAL_NOMBRE}: se intenta revertir {cantidad} "
                        f"unidades y solo hay {disponible} disponibles."
                    )

            previous_data = self._compra_snapshot(purchase, details)
            purchase.status = 'ANNULLED'

            for detail in details:
                inventory_record = self._get_inventory(detail.product_id)
                prev_qty = (Decimal(str(inventory_record.current_quantity))
                            if inventory_record is not None else CERO)
                nuevo_qty = prev_qty - Decimal(str(detail.quantity))
                if inventory_record is not None:
                    inventory_record.current_quantity = nuevo_qty
                self._write_audit(
                    user_id, "ANULACION_COMPRA", "NORMAL",
                    detail.product_id,
                    detail.lot_number,
                    prev_qty, nuevo_qty,
                    f"Anulación de compra (Lote: {detail.lot_number})"
                )

            audit_log = PurchaseAuditLog(
                purchase_id=purchase.id,
                action_type='ANNULLED',
                previous_data=previous_data,
                new_data=None,
                user_id=user_id
            )
            self.db.session.add(audit_log)
            self.db.session.commit()
            return True
        except ValueError as ve:
            self.db.session.rollback()
            raise ve
        except Exception as e:
            self.db.session.rollback()
            raise Exception(f"Error interno: {str(e)}")

    # ------------------------------------------------------------------
    # Edición lógica
    # ------------------------------------------------------------------
    # lot_number es VARCHAR(50) en BD: el correlativo no puede excederlo o el
    # INSERT falla con StringDataRightTruncation.
    LOT_MAX_LEN = 50

    def _generar_lote(self, product, purchase, contador=None):
        """Correlativo SKU-YYYYMMDD-NN para el producto en esa fecha de compra."""
        prod_sku = product.sku if product is not None and product.sku else f"PROD{product.id if product else 0}"
        date_str = (purchase.purchase_date.strftime('%Y%m%d')
                    if purchase.purchase_date
                    else datetime.now(UTC).strftime('%Y%m%d'))
        # Se reserva el espacio del sufijo "-YYYYMMDD-NN" (con margen para
        # correlativos de hasta 4 dígitos) y el resto se le entrega al SKU;
        # un SKU de 50 caracteres no cabe completo.
        max_sku_len = self.LOT_MAX_LEN - len(f"-{date_str}-") - 4
        if len(prod_sku) > max_sku_len:
            prod_sku = prod_sku[:max_sku_len]
        existentes = (self.db.session.query(PurchaseDetail.lot_number)
                      .filter(PurchaseDetail.lot_number.like(f"{prod_sku}-{date_str}-%"))
                      .with_for_update()
                      .all())
        max_seq = 0
        for (l_num,) in existentes:
            if l_num:
                try:
                    seq = int(str(l_num).split('-')[-1])
                    if seq > max_seq:
                        max_seq = seq
                except (ValueError, IndexError):
                    pass
        # El contador evita que dos anexos del mismo producto en una misma
        # edición reciban el mismo lote.
        if contador is not None and contador.get(prod_sku, 0) > max_seq:
            max_seq = contador[prod_sku]
        seq = max_seq + 1
        if contador is not None:
            contador[prod_sku] = seq
        return f"{prod_sku}-{date_str}-{seq:02d}"

    def logical_edit(self, purchase_id, user_id, new_items, reason):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status != 'COMPLETED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(
                purchase_id=purchase_id).all()
            detalles_por_id = {str(d.id): d for d in details}

            # -------- Fase 1: interpretar la entrada sin tocar la BD --------
            cambios = {}
            for item in new_items:
                item_id = str(item.get('id') or '')
                if item_id.startswith('new_'):
                    continue
                if item_id not in detalles_por_id:
                    raise ValueError(
                        f"El insumo #{item_id} no pertenece a la compra Nro. {purchase_id}."
                    )
                if item_id in cambios:
                    raise ValueError(f"El insumo #{item_id} aparece duplicado en la edición.")
                detail = detalles_por_id[item_id]
                # Solo se pisa el vencimiento/lote si el cliente envía la clave:
                # antes se anulaba siempre que viniera vacía, borrando la fecha
                # de vencimiento calculada del lote.
                cambios[item_id] = {
                    'detail': detail,
                    'quantity': parsear_decimal(
                        item.get('quantity'), 'cantidad',
                        Decimal('0.01'), Decimal('999999.99')),
                    'foreign_price': parsear_decimal(
                        item.get('foreign_price'), 'precio unitario',
                        Decimal('0.01'), Decimal('9999999.99')
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                    'expiration_date': (parsear_fecha(item.get('expiration_date'))
                                        if 'expiration_date' in item
                                        else detail.expiration_date),
                    'lot_number': ((str(item.get('lot_number')).strip() or None)
                                   if 'lot_number' in item
                                   else detail.lot_number),
                }

            nuevos = []
            for item in new_items:
                if not str(item.get('id') or '').startswith('new_'):
                    continue
                product_id = int(item['product_id'])
                product = self._get_product(product_id)
                if not product:
                    raise ValueError(
                        f"El producto con id {product_id} no existe y no puede añadirse."
                    )
                nuevos.append({
                    'product': product,
                    'product_id': product_id,
                    'quantity': parsear_decimal(
                        item.get('quantity'), 'cantidad',
                        Decimal('0.01'), Decimal('999999.99')),
                    # foreign_price llega como PRECIO UNITARIO (lo que muestra el
                    # modal de edición). Antes se dividía entre la cantidad, como
                    # en el registro de compras donde el campo es total de línea,
                    # y el total de la factura quedaba dividido por la cantidad.
                    'foreign_price': parsear_decimal(
                        item.get('foreign_price'), 'precio unitario',
                        Decimal('0.01'), Decimal('9999999.99')
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                    'expiration_date': (parsear_fecha(item.get('expiration_date'))
                                        if 'expiration_date' in item else None),
                    'lot_number': (str(item.get('lot_number')).strip() or None
                                   if item.get('lot_number') else None),
                })

            # -------- Fase 2: validar el impacto neto de stock --------------
            # Se valida el delta NETO por producto: la validación por renglón
            # rechazaba ediciones válidas (subir un renglón y bajar otro del
            # mismo producto) y aun así dejaba pasar duplicados.
            delta_por_producto = {}
            for item_id, cambio in cambios.items():
                detail = cambio['detail']
                delta = cambio['quantity'] - Decimal(str(detail.quantity))
                delta_por_producto[detail.product_id] = (
                    delta_por_producto.get(detail.product_id, CERO) + delta)
            for nuevo in nuevos:
                delta_por_producto[nuevo['product_id']] = (
                    delta_por_producto.get(nuevo['product_id'], CERO)
                    + nuevo['quantity'])
            # Los renglones que el cliente NO envía quedan eliminados de la
            # compra y en la Fase 3 se les resta su cantidad del inventario.
            # Si no se contabilizan aquí, esa resta se aplicaba sin validar
            # disponibilidad y el stock podía quedar negativo.
            for detail in details:
                if str(detail.id) not in cambios:
                    delta_por_producto[detail.product_id] = (
                        delta_por_producto.get(detail.product_id, CERO)
                        - Decimal(str(detail.quantity)))

            for product_id, delta in delta_por_producto.items():
                if delta >= CERO:
                    continue
                disponible = self._disponible(self._get_inventory(product_id))
                if disponible + delta < CERO:
                    product = self._get_product(product_id)
                    prod_name = product.name if product else f"ID {product_id}"
                    raise ValueError(
                        f"No se puede reducir el stock de '{prod_name}'. Se "
                        f"intentarían restar {abs(delta)} unidades y solo hay "
                        f"{disponible} disponibles en el {ALMACEN_CENTRAL_NOMBRE}."
                    )

            # -------- Fase 3: aplicar ---------------------------------------
            previous_data = self._compra_snapshot(purchase, details)
            tasa = self._resolve_exchange_rate(purchase)
            es_bs = es_moneda_bs(purchase.currency)
            new_total_amount = CERO

            for detail in details:
                item_id = str(detail.id)
                cambio = cambios.get(item_id)

                if cambio is None:
                    # Renglón quitado de la compra: se revierte el stock.
                    revert_qty = Decimal(str(detail.quantity))
                    inventory_record = self._get_inventory(detail.product_id)
                    prev_qty = (Decimal(str(inventory_record.current_quantity))
                                if inventory_record is not None else CERO)
                    nuevo_qty = prev_qty - revert_qty
                    if inventory_record is not None:
                        inventory_record.current_quantity = nuevo_qty
                    self._write_audit(
                        user_id, "AJUSTE_COMPRA", "NORMAL",
                        detail.product_id,
                        detail.lot_number,
                        prev_qty, nuevo_qty,
                        f"Insumo eliminado de la compra (Lote: {detail.lot_number})"
                    )
                    self.db.session.delete(detail)
                    continue

                old_qty = Decimal(str(detail.quantity))
                old_price = (Decimal(str(detail.foreign_price))
                             if detail.foreign_price is not None else CERO)
                old_exp = detail.expiration_date
                old_lot = detail.lot_number

                new_qty = cambio['quantity']
                new_price = cambio['foreign_price']
                qty_diff = new_qty - old_qty

                inventory_record = self._get_inventory(detail.product_id)
                if inventory_record is not None:
                    prev_qty = Decimal(str(inventory_record.current_quantity))
                    inventory_record.current_quantity = prev_qty + qty_diff
                elif qty_diff > CERO:
                    inventory_record, prev_qty = self._get_or_create_inventory(
                        detail.product_id, qty_diff)
                else:
                    prev_qty = CERO

                new_price_bs = (new_price if es_bs
                                else (new_price * tasa).quantize(
                                    Decimal('0.01'), rounding=ROUND_HALF_UP))

                detail.quantity = new_qty
                detail.foreign_price = new_price
                detail.price_bs = new_price_bs
                detail.expiration_date = cambio['expiration_date']
                detail.lot_number = cambio['lot_number']

                if (qty_diff != CERO
                        or new_price != old_price
                        or cambio['expiration_date'] != old_exp
                        or (cambio['lot_number'] or '') != (old_lot or '')):
                    self._write_audit(
                        user_id, "AJUSTE_COMPRA",
                        self._severidad(self._get_product(detail.product_id),
                                        old_qty, new_qty),
                        detail.product_id,
                        cambio['lot_number'],
                        old_qty, new_qty,
                        f"Ajuste por edición de compra (Lote: {cambio['lot_number']})"
                    )

                new_total_amount += (new_qty * new_price)

            contador_lotes = {}
            for nuevo in nuevos:
                exp_date_obj = nuevo['expiration_date']
                if exp_date_obj is None and getattr(nuevo['product'], 'product_type_id', None):
                    p_type = self.db.session.get(ProductType, nuevo['product'].product_type_id)
                    if p_type is not None and getattr(p_type, 'shelf_life_days', None):
                        exp_date_obj = (datetime.now() + timedelta(days=p_type.shelf_life_days)).date()

                lot_val = nuevo['lot_number'] or self._generar_lote(
                    nuevo['product'], purchase, contador_lotes)

                new_detail = PurchaseDetail(
                    purchase_id=purchase.id,
                    product_id=nuevo['product_id'],
                    quantity=nuevo['quantity'],
                    foreign_price=nuevo['foreign_price'],
                    price_bs=(nuevo['foreign_price'] if es_bs
                              else (nuevo['foreign_price'] * tasa).quantize(
                                  Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    expiration_date=exp_date_obj,
                    lot_number=lot_val
                )
                self.db.session.add(new_detail)

                inventory_record, inv_prev = self._get_or_create_inventory(
                    nuevo['product_id'], nuevo['quantity'])
                inv_nuevo = inv_prev + nuevo['quantity']
                inventory_record.current_quantity = inv_nuevo

                self._write_audit(
                    user_id, "AJUSTE_COMPRA",
                    self._severidad(nuevo['product'], inv_prev, inv_nuevo),
                    nuevo['product_id'], lot_val,
                    inv_prev, inv_nuevo,
                    f"Nuevo insumo añadido por edición de compra (Lote: {lot_val})"
                )

                new_total_amount += (nuevo['quantity'] * nuevo['foreign_price'])
                # Flush para que el siguiente lote generado vea este renglón.
                self.db.session.flush()

            purchase.total_amount = new_total_amount.quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)

            final_details = self.db.session.query(PurchaseDetail).filter_by(
                purchase_id=purchase_id).all()

            new_data = self._compra_snapshot(purchase, final_details)
            new_data['edit_reason'] = reason

            audit_log = PurchaseAuditLog(
                purchase_id=purchase.id,
                action_type='EDIT',
                previous_data=previous_data,
                new_data=new_data,
                user_id=user_id
            )
            self.db.session.add(audit_log)
            self.db.session.commit()
            return True
        except ValueError as ve:
            self.db.session.rollback()
            raise ve
        except Exception as e:
            self.db.session.rollback()
            raise Exception(f"Error interno: {str(e)}")
