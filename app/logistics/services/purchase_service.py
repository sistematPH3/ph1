from decimal import ROUND_HALF_UP, Decimal
import json
import re
from flask import current_app
from sqlalchemy import text
from app.extensions import db
from app.models.logistics_model import Purchase, PurchaseDetail
from app.models import PurchaseAuditLog, Inventory
from app.models.inventory_model import Product
from app.logistics.requests.purchase_validators import (
    normalizar_numero,
    normalizar_moneda,
)
from app.time_utils import current_ve_time

class PurchaseService:
    @staticmethod
    def register_purchase(data):
        try:
            items = data.get('items') or []
            if not items:
                return {
                    'success': False,
                    'message': 'La compra debe tener al menos un producto.'
                }

            purchase_date = current_ve_time()
            # Se usa normalizar_moneda y no la limpieza propia de antes: el
            # validador ya reconocia 'BS,S', 'BS.', 'BSS', 'BOLIVAR', etc.
            # como bolívares, pero aqui la comparacion contra ('VES','BS')
            # no los cubria, asi que una compra en 'BS,S' pasaba la validacion
            # como bolivares y despues se guardaba como estranjera,
            # multiplicando el monto por la tasa (3.000 Bs x 36,5 = 109.500).
            currency = normalizar_moneda(data['currency'])

            exchange_rate = Decimal(normalizar_numero(data['exchange_rate']))
            if not exchange_rate.is_finite() or exchange_rate <= 0:
                raise ValueError(
                    'La tasa de cambio debe ser un número mayor que cero.')

            # Se valida cada linea ANTES de crear la cabecera. Antes una
            # cantidad en cero reventaba con DivisionByZero y una negativa
            # pasaba, dejando stock restado y totales sin sentido.
            for indice, item in enumerate(items, start=1):
                cantidad = Decimal(normalizar_numero(item.get('quantity')))
                importe = Decimal(normalizar_numero(item.get('foreign_price')))
                for etiqueta, valor in (('cantidad', cantidad),
                                        ('importe', importe)):
                    if not valor.is_finite():
                        raise ValueError(
                            f'Línea {indice}: la {etiqueta} no es un número válido.')
                    if valor <= 0:
                        raise ValueError(
                            f'Línea {indice}: la {etiqueta} debe ser mayor que cero.')

            new_purchase = Purchase(
                supplier_id=data['supplier_id'],
                purchase_date=purchase_date,
                total_amount=Decimal('0.00'),
                currency=currency,
                exchange_rate=exchange_rate,
                user_id=data['user_id'],
                invoice_url=data.get('invoice_url'), 
                status='COMPLETED' 
            )
            db.session.add(new_purchase)
            db.session.flush()

            calculated_total = Decimal('0.00')
            es_bs = currency == 'BS'
            
            details_for_audit = []
            sku_lot_counters = {}

            for item in items:
                product_id = int(item['product_id'])
                quantity = Decimal(normalizar_numero(item.get('quantity', 0.0)))
                # El precio registrado es el TOTAL pagado por toda la cantidad de
                # ese producto (según la moneda seleccionada). Se divide entre la
                # cantidad para almacenarlo por unidad.
                linea_total = Decimal(normalizar_numero(item['foreign_price']))
                foreign_price = (linea_total / quantity).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)

                # En Bs el precio ya es bolívares: no se vuelve a multiplicar por la tasa.
                # Se cuantiza siempre, como hace la edicion de compras: la columna
                # es Numeric(15,2) y antes se mandaba el producto sin redondear,
                # de modo que el registro y la edicion redondeaban distinto.
                price_bs = (foreign_price if es_bs
                            else (foreign_price * exchange_rate).quantize(
                                Decimal('0.01'), rounding=ROUND_HALF_UP))

                # El total de la cabecera es la suma de los importes que el
                # usuario escribio por linea (lo que realmente se pago), y NO
                # se reconstruye multiplicando el precio unitario ya redondeado
                # por la cantidad: eso daria 3,33 x 3 = 9,99 contra un total de
                # 10,00, y ademas descuadaria la regla de que las cantidades no
                # multiplican el importe de la linea. El redondeo a 2 decimales
                # del precio unitario es propio de como se guarda el detalle.
                calculated_total += linea_total

                producto_obj = db.session.query(Product).get(product_id)
                prod_name = producto_obj.name if producto_obj else f"Insumo ID {product_id}"
                prod_sku = producto_obj.sku if producto_obj and producto_obj.sku else f"PROD{product_id}"

                lot_number = item.get('lot_number')
                if not lot_number or not str(lot_number).strip():
                    date_str = purchase_date.strftime('%Y%m%d')
                    if prod_sku not in sku_lot_counters:
                        # '_' es comodin en LIKE: un SKU como 'CAFE_01' también
                        # encontraba los lotes de 'CAFEX01' y la secuencia
                        # arrancaba mas alta de lo que debia. Se escapan los
                        # comodines del SKU antes de usarlo como patron.
                        patron_sku = (prod_sku
                                      .replace('\\', '\\\\')
                                      .replace('%', '\\%')
                                      .replace('_', '\\_'))
                        existing_lots = db.session.query(PurchaseDetail.lot_number).filter(
                            PurchaseDetail.lot_number.like(
                                f"{patron_sku}-{date_str}-%", escape='\\')
                        ).all()
                        max_seq = 0
                        for (l_num,) in existing_lots:
                            if l_num:
                                try:
                                    parts = l_num.split('-')
                                    seq = int(parts[-1])
                                    if seq > max_seq:
                                        max_seq = seq
                                except (ValueError, IndexError):
                                    pass
                        sku_lot_counters[prod_sku] = max_seq

                    sku_lot_counters[prod_sku] += 1
                    lot_number = f"{prod_sku}-{date_str}-{sku_lot_counters[prod_sku]:02d}"
                else:
                    lot_number = str(lot_number).strip()

                new_detail = PurchaseDetail(
                    purchase_id=new_purchase.id,
                    product_id=product_id,
                    quantity=quantity,
                    foreign_price=foreign_price,
                    price_bs=price_bs,
                    expiration_date=item.get('expiration_date'),
                    lot_number=lot_number
                )
                db.session.add(new_detail)

                details_for_audit.append({
                    "product_id": product_id,
                    "quantity": float(quantity),
                    "foreign_price": float(foreign_price),
                    "price_bs": float(price_bs),
                    "expiration_date": str(item.get('expiration_date')) if item.get('expiration_date') else None,
                    "lot_number": lot_number
                })

                # Búsqueda o creación de inventario (min_stock lo define la
                # configuración previa; aquí NO se fuerza ningún valor).
                inventory_record = db.session.query(Inventory).filter_by(
                    location_id=1, 
                    product_id=product_id
                ).first()
                
                if inventory_record:
                    prev_qty = Decimal(str(inventory_record.current_quantity))
                    inventory_record.current_quantity = prev_qty + quantity
                else:
                    prev_qty = Decimal('0.00')
                    # min_stock lo define el insumo (producto) o 20 por defecto.
                    _min = producto_obj.min_stock_efectivo if producto_obj else Decimal('20.00')
                    new_inv = Inventory(
                        location_id=1, 
                        product_id=product_id, 
                        current_quantity=quantity,
                        min_stock=_min,
                        transit_quantity=Decimal('0.00')
                    )
                    db.session.add(new_inv)

                new_qty = prev_qty + quantity

                changed_data = {
                    "location_id": 1,
                    "location_name": "Almacén Central",
                    "product_id": product_id,
                    "product_name": prod_name,
                    "lot_number": lot_number,
                    "previous_quantity": float(prev_qty),
                    "new_quantity": float(new_qty),
                    "quantity_changed": float(quantity),
                    "notes": f"Ingreso por compra a proveedor (Lote: {lot_number})"
                }
                
                # El mínimo es el configurado para el producto; antes se usaba
                # un 20 fijo que clasificaba mal a productos con otro mínimo.
                minimo = (producto_obj.min_stock_efectivo
                          if producto_obj else Decimal('20.00'))
                severity = ('REABASTECIDO'
                            if prev_qty <= minimo < new_qty else 'NORMAL')
                
                db.session.execute(text("""
                    INSERT INTO audit_logs (user_id, action, severity, location_id, changed_data, timestamp)
                    VALUES (:uid, 'INGRESO_COMPRA', :sev, 1, :cdata, :ts)
                """), {
                    'uid': data['user_id'],
                    'sev': severity,
                    'cdata': json.dumps(changed_data),
                    'ts': current_ve_time()
                })

            new_purchase.total_amount = calculated_total.quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            new_data_audit = {
                "id": new_purchase.id,
                "supplier_id": new_purchase.supplier_id,
                "total_amount": float(calculated_total),
                "currency": new_purchase.currency,
                "exchange_rate": float(exchange_rate),
                "status": new_purchase.status,
                "details": details_for_audit
            }
            
            audit_log = PurchaseAuditLog(
                purchase_id=new_purchase.id,
                action_type='CREATE',
                previous_data={},
                new_data=new_data_audit,
                user_id=data['user_id']
            )
            db.session.add(audit_log)

            db.session.commit()
            
            return {
                "success": True, 
                "message": "Compra registrada y stock general actualizado con éxito.",
                "purchase_id": new_purchase.id
            }

        except ValueError as e:
            # Errores de los datos que escribio el usuario (tasa en cero,
            # cantidad en cero, guion bajo como separador de miles). El texto
            # es del propio codigo de validacion, no una excepcion interna, asi
            # que si se le puede mostrar tal cual para que sepa que corregir.
            db.session.rollback()
            return {
                "success": False,
                "message": str(e),
                "error": str(e),
            }

        except Exception as e:
            db.session.rollback()
            # Antes la excepcion se guardaba solo en el mensaje de respuesta y
            # no se logueaba en ningun lado: un fallo al registrar una compra
            # no dejaba ni una linea en el log del servidor, y el texto con el
            # SQL y sus parametros se mandaba de vuelta al navegador.
            current_app.logger.error(
                "No se pudo registrar la compra: %s", e, exc_info=True,
            )
            # El detalle va al log, nunca a la respuesta: la excepcion incluye
            # el SQL y sus parametros.
            return {
                "success": False,
                "message": "No se pudo registrar la compra.",
                "error": (
                    "No se pudo registrar la compra. Los datos no se guardaron: "
                    "vuelve a intentarlo y, si sigue fallando, avisa al responsable."
                ),
            }
