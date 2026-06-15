# app/logistics/services/purchase_service.py
from datetime import datetime
from decimal import Decimal  # <-- IMPORTANTE: Añade esta importación
from app.extensions import db
from app.models.logistics_model import Purchase, PurchaseDetail, Location
from app.models.inventory_model import Inventory

class PurchaseService:
    @staticmethod
    def register_purchase(data):
        try:
            # 1. Crear la cabecera de la compra
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

            # Convertimos la tasa a Decimal pasándola primero por string para mantener precisión exacta
            exchange_rate = Decimal(str(data['exchange_rate']))
            calculated_total = Decimal('0.0')

            # 2. Registrar los detalles y calcular Multi-Moneda
            for item in data['items']:
                # Convertimos cantidades y precios a Decimal
                quantity = Decimal(str(item.get('quantity', 0)))
                foreign_price = Decimal(str(item['foreign_price']))
                
                # Operaciones seguras entre Decimals
                price_bs = foreign_price * exchange_rate
                calculated_total += (foreign_price * quantity)

                new_detail = PurchaseDetail(
                    purchase_id=new_purchase.id,
                    product_id=item['product_id'],
                    quantity=quantity,
                    foreign_price=foreign_price,
                    price_bs=price_bs
                )
                db.session.add(new_detail)

                # 3. Actualizar Impacto en Inventario
                inventory_item = Inventory.query.filter_by(product_id=item['product_id']).first()
                
                if inventory_item:
                    # ¡AHORA SÍ! Decimal + Decimal funciona perfectamente
                    inventory_item.current_quantity += quantity
                else:
                    default_location = Location.query.first()
                    loc_id = default_location.id if default_location else 1
                    
                    new_inventory = Inventory(
                        product_id=item['product_id'],
                        location_id=loc_id,   
                        current_quantity=quantity 
                    )
                    db.session.add(new_inventory)

            # Actualizar el total real calculado de la factura
            new_purchase.total_amount = calculated_total

            db.session.commit()
            
            return {
                "success": True, 
                "message": "Compra registrada e inventario actualizado con éxito.",
                "purchase_id": new_purchase.id
            }

        except Exception as e:
            db.session.rollback()
            return {
                "success": False, 
                "message": f"Error crítico al registrar la compra: {str(e)}"
            }