from datetime import datetime
from decimal import Decimal
from app.extensions import db
from app.models.logistics_model import Purchase, PurchaseDetail
from app.models.inventory_model import Product
from app.models import PurchaseAuditLog

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

            calculated_total = 0.0
            exchange_rate = float(data['exchange_rate'])
            
            details_for_audit = []

            for item in data['items']:
                quantity = int(float(item.get('quantity', 0)))
                foreign_price = float(item['foreign_price'])
                
                price_bs = foreign_price * exchange_rate
                calculated_total += (foreign_price * quantity)

                new_detail = PurchaseDetail(
                    purchase_id=new_purchase.id,
                    product_id=item['product_id'],
                    quantity=float(quantity),
                    foreign_price=foreign_price,
                    price_bs=price_bs,
                    expiration_date=item.get('expiration_date')
                )
                db.session.add(new_detail)

                details_for_audit.append({
                    "product_id": item['product_id'],
                    "quantity": float(quantity),
                    "foreign_price": foreign_price,
                    "price_bs": price_bs,
                    "expiration_date": str(item.get('expiration_date')) if item.get('expiration_date') else None
                })

                # Actualización exclusiva del Stock General (Almacén Nacional)
                product = Product.query.get(item['product_id'])
                if product:
                    product.quantity += quantity

            new_purchase.total_amount = calculated_total
            
            new_data_audit = {
                "id": new_purchase.id,
                "supplier_id": new_purchase.supplier_id,
                "total_amount": float(calculated_total),
                "currency": new_purchase.currency,
                "exchange_rate": exchange_rate,
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