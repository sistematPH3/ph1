from app.models import Purchase, PurchaseDetail, Supplier, PurchaseAuditLog, Product, ProductType, Inventory
from decimal import Decimal
from datetime import datetime, timedelta

class PurchaseManagementRepository:
    def __init__(self, db_connection):
        self.db = db_connection

    def get_filtered_history(self, start_date=None, end_date=None, supplier_id=None, status=None):
        query = self.db.session.query(Purchase, Supplier.name.label('supplier_name')).join(
            Supplier, Purchase.supplier_id == Supplier.id
        )
        
        if start_date:
            query = query.filter(Purchase.purchase_date >= start_date)
        if end_date:
            query = query.filter(Purchase.purchase_date <= end_date)
            
        if supplier_id:
            query = query.filter(Purchase.supplier_id == supplier_id)
            
        if status:
            query = query.filter(Purchase.status == status)
            
        return query.order_by(Purchase.purchase_date.desc()).all()

    def get_purchase_by_id(self, purchase_id):
        return self.db.session.query(Purchase).get(purchase_id)

    def get_details_by_purchase_id(self, purchase_id):
        return self.db.session.query(
            PurchaseDetail, 
            Product.sku.label('product_sku'),
            ProductType.requires_manual_date.label('requires_manual_date')
        ).join(Product, PurchaseDetail.product_id == Product.id)\
         .outerjoin(ProductType, Product.product_type_id == ProductType.id)\
         .filter(PurchaseDetail.purchase_id == purchase_id).all()
            
    def logical_annulment(self, purchase_id, user_id):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status == 'ANNULLED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(purchase_id=purchase_id).all()

            for detail in details:
                inventory_record = self.db.session.query(Inventory).filter_by(
                    location_id=1, 
                    product_id=detail.product_id
                ).first()
                
                qty_to_remove = Decimal(str(detail.quantity))
                
                if not inventory_record or inventory_record.current_quantity < qty_to_remove:
                    product = self.db.session.query(Product).get(detail.product_id)
                    prod_name = product.name if product else f"ID {detail.product_id}"
                    raise ValueError(f"No se puede anular. Stock insuficiente de '{prod_name}' en el Almacén Central para revertir {qty_to_remove} unidades.")

            previous_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount) if purchase.total_amount else 0.0,
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate else 0.0,
                "status": purchase.status,
                "details": [
                    {
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price) if d.foreign_price else 0.0,
                        "price_bs": float(d.price_bs) if d.price_bs else 0.0,
                        "expiration_date": str(d.expiration_date) if getattr(d, 'expiration_date', None) else None
                    } for d in details
                ]
            }

            purchase.status = 'ANNULLED'

            for detail in details:
                inventory_record = self.db.session.query(Inventory).filter_by(
                    location_id=1, 
                    product_id=detail.product_id
                ).first()
                
                inventory_record.current_quantity -= Decimal(str(detail.quantity))

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

    def logical_edit(self, purchase_id, user_id, new_items, reason):
        try:
            purchase = self.get_purchase_by_id(purchase_id)
            if not purchase or purchase.status == 'ANNULLED':
                return False

            details = self.db.session.query(PurchaseDetail).filter_by(purchase_id=purchase_id).all()

            for detail in details:
                matching_new = next((item for item in new_items if str(item['id']) == str(detail.id)), None)
                if matching_new:
                    new_qty = Decimal(str(matching_new['quantity']))
                    old_qty = Decimal(str(detail.quantity))
                    qty_diff = new_qty - old_qty
                    
                    if qty_diff < Decimal('0.00'): 
                        abs_diff = abs(qty_diff)
                        inventory_record = self.db.session.query(Inventory).filter_by(
                            location_id=1, 
                            product_id=detail.product_id
                        ).first()
                        
                        if not inventory_record or inventory_record.current_quantity < abs_diff:
                            product = self.db.session.query(Product).get(detail.product_id)
                            prod_name = product.name if product else f"ID {detail.product_id}"
                            raise ValueError(f"No se puede reducir la cantidad de '{prod_name}'. Se intentan restar {abs_diff} unidades, pero el stock actual es insuficiente.")

            previous_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount) if purchase.total_amount else 0.0,
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate) if purchase.exchange_rate else 0.0,
                "status": purchase.status,
                "details": [
                    {
                        "id": d.id,
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price) if d.foreign_price else 0.0,
                        "price_bs": float(d.price_bs) if d.price_bs else 0.0,
                        "expiration_date": str(d.expiration_date) if getattr(d, 'expiration_date', None) else None
                    } for d in details
                ]
            }

            new_total_amount = Decimal('0.00')
            purchase_exchange_rate = Decimal(str(purchase.exchange_rate))

            for detail in details:
                matching_new = next((item for item in new_items if str(item['id']) == str(detail.id)), None)
                
                if matching_new:
                    new_qty = Decimal(str(matching_new['quantity']))
                    new_price = Decimal(str(matching_new['foreign_price']))
                    old_qty = Decimal(str(detail.quantity))
                    
                    qty_diff = new_qty - old_qty
                    
                    if qty_diff != Decimal('0.00'):
                        inventory_record = self.db.session.query(Inventory).filter_by(
                            location_id=1, 
                            product_id=detail.product_id
                        ).first()
                        
                        if inventory_record:
                            inventory_record.current_quantity += qty_diff
                        elif qty_diff > Decimal('0.00'):
                            new_inv = Inventory(
                                location_id=1, 
                                product_id=detail.product_id, 
                                current_quantity=qty_diff
                            )
                            self.db.session.add(new_inv)
                    
                    detail.quantity = new_qty
                    detail.foreign_price = new_price
                    detail.price_bs = new_price * purchase_exchange_rate
                    
                    if 'expiration_date' in matching_new and matching_new['expiration_date']:
                        detail.expiration_date = datetime.strptime(matching_new['expiration_date'], '%Y-%m-%d').date()
                    else:
                        detail.expiration_date = None

                    new_total_amount += (new_qty * new_price)
                else:
                    new_total_amount += (Decimal(str(detail.quantity)) * Decimal(str(detail.foreign_price)))

            for item in new_items:
                if str(item['id']).startswith('new_'):
                    if not item.get('product_id'):
                        continue
                        
                    new_qty = Decimal(str(item['quantity']))
                    new_price = Decimal(str(item['foreign_price']))
                    product_id = int(item['product_id'])
                    
                    exp_date_obj = None
                    if item.get('expiration_date'):
                        exp_date_obj = datetime.strptime(item['expiration_date'], '%Y-%m-%d').date()
                    else:
                        product = self.db.session.query(Product).filter_by(id=product_id).first()
                        if product and getattr(product, 'product_type_id', None):
                            p_type = self.db.session.query(ProductType).filter_by(id=product.product_type_id).first()
                            if p_type and getattr(p_type, 'shelf_life_days', None):
                                exp_date_obj = (datetime.now() + timedelta(days=p_type.shelf_life_days)).date()

                    new_detail = PurchaseDetail(
                        purchase_id=purchase.id,
                        product_id=product_id,
                        quantity=new_qty,
                        foreign_price=new_price,
                        price_bs=new_price * purchase_exchange_rate,
                        expiration_date=exp_date_obj
                    )
                    self.db.session.add(new_detail)
                    
                    inventory_record = self.db.session.query(Inventory).filter_by(
                        location_id=1, 
                        product_id=product_id
                    ).first()
                    
                    if inventory_record:
                        inventory_record.current_quantity += new_qty
                    else:
                        new_inv = Inventory(
                            location_id=1, 
                            product_id=product_id, 
                            current_quantity=new_qty
                        )
                        self.db.session.add(new_inv)

                    new_total_amount += (new_qty * new_price)

            self.db.session.flush()

            purchase.total_amount = new_total_amount
            
            final_details = self.db.session.query(PurchaseDetail).filter_by(purchase_id=purchase_id).all()

            new_data = {
                "id": purchase.id,
                "supplier_id": purchase.supplier_id,
                "total_amount": float(purchase.total_amount),
                "currency": purchase.currency,
                "exchange_rate": float(purchase.exchange_rate),
                "status": purchase.status,
                "edit_reason": reason,
                "details": [
                    {
                        "id": d.id,
                        "product_id": d.product_id,
                        "quantity": float(d.quantity),
                        "foreign_price": float(d.foreign_price),
                        "price_bs": float(d.price_bs),
                        "expiration_date": str(d.expiration_date) if getattr(d, 'expiration_date', None) else None
                    } for d in final_details
                ]
            }

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