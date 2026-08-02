from datetime import datetime
from decimal import Decimal
import json
from sqlalchemy import text
from app.extensions import db
from app.models.logistics_model import Purchase, PurchaseDetail
from app.models import PurchaseAuditLog, Inventory
from app.models.inventory_model import Product

class PurchaseService:
    @staticmethod
    def register_purchase(data):
        try:
            new_purchase = Purchase(
                supplier_id=data['supplier_id'],
                purchase_date=datetime.utcnow(),
                total_amount=data.get('total_amount', 0.0),
                currency=data['currency'].upper(),
                exchange_rate=data['exchange_rate'],
                user_id=data['user_id'],
                invoice_url=data.get('invoice_url'), 
                status='COMPLETED' 
            )
            db.session.add(new_purchase)
            db.session.flush()

            calculated_total = Decimal('0.00')
            exchange_rate = Decimal(str(data['exchange_rate']))
            
            details_for_audit = []

            for item in data['items']:
                product_id = int(item['product_id'])
                quantity = Decimal(str(item.get('quantity', 0.0)))
                foreign_price = Decimal(str(item['foreign_price']))
                
                price_bs = foreign_price * exchange_rate
                calculated_total += (foreign_price * quantity)

                new_detail = PurchaseDetail(
                    purchase_id=new_purchase.id,
                    product_id=product_id,
                    quantity=quantity,
                    foreign_price=foreign_price,
                    price_bs=price_bs,
                    expiration_date=item.get('expiration_date')
                )
                db.session.add(new_detail)

                details_for_audit.append({
                    "product_id": product_id,
                    "quantity": float(quantity),
                    "foreign_price": float(foreign_price),
                    "price_bs": float(price_bs),
                    "expiration_date": str(item.get('expiration_date')) if item.get('expiration_date') else None
                })

                # --- MAGIA DEL INVENTARIO CORREGIDA PARA AUDITORÍA ---
                inventory_record = db.session.query(Inventory).filter_by(
                    location_id=1, 
                    product_id=product_id
                ).first()
                
                # Capturamos el stock real que ya existía antes de sumar la compra
                if inventory_record:
                    prev_qty = float(inventory_record.current_quantity)
                    inventory_record.current_quantity = Decimal(str(inventory_record.current_quantity)) + quantity
                else:
                    prev_qty = 0.0
                    new_inv = Inventory(
                        location_id=1, 
                        product_id=product_id, 
                        current_quantity=quantity
                    )
                    db.session.add(new_inv)

                new_qty = prev_qty + float(quantity)

                # Buscamos el nombre del producto para el JSON
                producto_obj = db.session.query(Product).get(product_id)
                prod_name = producto_obj.name if producto_obj else f"Insumo ID {product_id}"
                
                # Estructura exacta que espera tu frontend para mostrar las cantidades
                changed_data = {
                    "location_id": 1,
                    "location_name": "Almacén Central",
                    "product_id": product_id,
                    "product_name": prod_name,
                    "previous_quantity": prev_qty,
                    "new_quantity": new_qty,
                    "quantity_changed": float(quantity),
                    "notes": "Ingreso por compra a proveedor"
                }
                
                severity = 'REABASTECIDO' if prev_qty <= 20 and new_qty > 20 else 'NORMAL'
                
                db.session.execute(text("""
                    INSERT INTO audit_logs (user_id, action, severity, location_id, changed_data, timestamp)
                    VALUES (:uid, 'INGRESO_COMPRA', :sev, 1, :cdata, :ts)
                """), {
                    'uid': data['user_id'],
                    'sev': severity,
                    'cdata': json.dumps(changed_data),
                    'ts': datetime.now()
                })

            new_purchase.total_amount = calculated_total
            
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

        except Exception as e:
            db.session.rollback()
            return {
                "success": False, 
                "message": f"Error crítico al registrar la compra: {str(e)}"
            }