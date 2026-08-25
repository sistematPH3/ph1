import json
from sqlalchemy import func
from app import db
from app.models import Inventory, Product, Location, user_locations
from app.models.logistics_model import Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import AuditLog

class InventoryViewRepository:
    
    @staticmethod
    def get_inventory_by_location(location_id, search_term=None):
        query = Inventory.query.join(Product).join(Location).filter(
            Inventory.location_id == location_id
        )
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_all_inventory(search_term=None):
        query = Inventory.query.join(Product).join(Location)
        
        if search_term:
            query = query.filter(
                Product.name.ilike(f"%{search_term}%") | 
                Product.sku.ilike(f"%{search_term}%")
            )
            
        return query.all()

    @staticmethod
    def get_user_assigned_locations(user_id):
        return Location.query.join(
            user_locations, 
            Location.id == user_locations.c.location_id
        ).filter(user_locations.c.user_id == user_id).all()

    @staticmethod
    def get_all_active_locations():
        return Location.query.filter_by(is_active=True).all()

    @staticmethod
    def get_low_stock_counts_by_location():
        results = db.session.query(
            Location.id,
            Location.name,
            func.count(Inventory.id).label('low_stock_count')
        ).join(Inventory, Location.id == Inventory.location_id)\
         .join(Product, Inventory.product_id == Product.id)\
         .filter(
            Location.is_active == True,
            Product.is_active == True,
            Inventory.current_quantity > 0,
            Inventory.current_quantity <= Inventory.min_stock
        ).group_by(Location.id, Location.name).all()

        return [
            {
                'location_id': r.id,
                'location_name': r.name,
                'count': r.low_stock_count
            } for r in results if r.low_stock_count > 0
        ]

    @staticmethod
    def get_product_lots_by_location(location_id, product_id):
        loc_id = int(location_id)
        prod_id = int(product_id)

        entradas_por_lote = {}
        salidas_traslados = {}

        if loc_id == 1:
            purchase_records = db.session.query(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date,
                func.sum(PurchaseDetail.quantity).label('total_qty')
            ).join(
                Purchase, PurchaseDetail.purchase_id == Purchase.id
            ).filter(
                func.upper(Purchase.status) == 'COMPLETED',
                PurchaseDetail.product_id == prod_id,
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).group_by(
                PurchaseDetail.lot_number,
                PurchaseDetail.expiration_date
            ).all()

            for r in purchase_records:
                lot = r.lot_number.strip()
                entradas_por_lote[lot] = {
                    'expiration_date': r.expiration_date,
                    'total_in': float(r.total_qty or 0.0)
                }

            movements_out = db.session.query(
                MovementDetail.lot_number,
                func.sum(MovementDetail.quantity).label('total_out')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                Movement.origin_location_id == 1,
                Movement.status.notin_(['ANULADO', 'CANCELADO', 'RECHAZADO']),
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None)
            ).group_by(MovementDetail.lot_number).all()

            salidas_traslados = {r.lot_number.strip(): float(r.total_out or 0.0) for r in movements_out if r.lot_number}

        else:
            valid_statuses = ['COMPLETED', 'NOVEDAD_FALTANTE', 'CERRADO_POR_ADMIN', 'CERRADO_CON_PERDIDA']
            movement_records = db.session.query(
                MovementDetail.lot_number,
                MovementDetail.expiration_date,
                func.sum(func.coalesce(MovementDetail.received_quantity, MovementDetail.quantity)).label('total_qty')
            ).join(
                Movement, MovementDetail.movement_id == Movement.id
            ).filter(
                func.upper(Movement.status).in_(valid_statuses),
                Movement.destination_location_id == loc_id,
                MovementDetail.product_id == prod_id,
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(
                MovementDetail.lot_number,
                MovementDetail.expiration_date
            ).all()

            for r in movement_records:
                lot = r.lot_number.strip()
                entradas_por_lote[lot] = {
                    'expiration_date': r.expiration_date,
                    'total_in': float(r.total_qty or 0.0)
                }

        audit_records = db.session.query(
            AuditLog.changed_data
        ).filter(
            AuditLog.location_id == loc_id,
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA', 'MERMA'])
        ).all()

        salidas_consumo = {}
        for (c_data,) in audit_records:
            if not c_data:
                continue
            if isinstance(c_data, str):
                try:
                    c_data = json.loads(c_data)
                except Exception:
                    continue
            if not isinstance(c_data, dict):
                continue
                
            p_id = c_data.get('product_id')
            l_num = c_data.get('lot_number')
            qty_change = c_data.get('quantity_changed', 0.0)
            
            if (p_id is None or int(p_id) == prod_id) and l_num and l_num != 'N/A':
                l_num_clean = str(l_num).strip()
                salidas_consumo[l_num_clean] = salidas_consumo.get(l_num_clean, 0.0) + abs(float(qty_change))

        lots = []
        for lot_num, data in entradas_por_lote.items():
            total_in = data['total_in']
            total_out_traslados = salidas_traslados.get(lot_num, 0.0)
            total_out_consumos = salidas_consumo.get(lot_num, 0.0)
            
            disponible = total_in - total_out_traslados - total_out_consumos
            
            if disponible > 0.001:
                lots.append({
                    'lot_number': lot_num,
                    'expiration_date': data['expiration_date'].strftime('%d/%m/%Y') if data['expiration_date'] else 'Sin vencimiento',
                    'exp_date_raw': data['expiration_date'],
                    'quantity': round(float(disponible), 2)
                })

        lots.sort(key=lambda x: (x['exp_date_raw'] is None, x['exp_date_raw']))
        
        for l in lots:
            l.pop('exp_date_raw', None)
            
        return lots