import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, or_
from app.time_utils import current_ve_time
from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import Waste, WasteType, WasteDetail, AppParameter, AuditLog
from app.models.security_model import User, Notification, user_locations
from app.inventory.services.lot_availability_service import _compute_lot_availability, get_expired_lots

class InsufficientStockError(Exception):
    pass

class RegisterWasteRepository:

    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_all_sedes():
        return Location.query.filter(Location.is_active == True).all()

    @staticmethod
    def get_central_sede():
        return Location.query.filter_by(id=1).first()

    @staticmethod
    def get_user_locations(user_id):
        loc_ids_result = db.session.query(user_locations.c.location_id).filter(
            user_locations.c.user_id == user_id).all()
        loc_ids = [row[0] for row in loc_ids_result]
        if not loc_ids:
            return []
        return Location.query.filter(Location.id.in_(loc_ids), Location.is_active == True).all()

    @staticmethod
    def get_waste_types():
        return WasteType.query.filter_by(is_active=True).order_by(WasteType.id).all()

    @staticmethod
    def get_waste_type_by_id(waste_type_id):
        return WasteType.query.get(waste_type_id)

    @staticmethod
    def get_waste_by_request_id(request_id):
        return Waste.query.filter_by(request_id=request_id).order_by(Waste.id.desc()).first()

    @staticmethod
    def get_products_in_inventory(location_id):
        return db.session.query(Product).join(
            Inventory, Product.id == Inventory.product_id
        ).filter(
            Inventory.location_id == location_id,
            Inventory.current_quantity > 0,
            Product.is_active == True
        ).all()

    @staticmethod
    def get_inventory_item(product_id, location_id):
        return Inventory.query.filter_by(
            product_id=product_id,
            location_id=location_id
        ).first()

    @staticmethod
    def get_inventory_map(location_id, product_ids):
        """Mapa {product_id: Inventory} para varios productos de una sede (evita N+1)."""
        ids = [int(p) for p in product_ids]
        if not ids:
            return {}
        invs = Inventory.query.filter(
            Inventory.location_id == int(location_id),
            Inventory.product_id.in_(ids)
        ).all()
        return {i.product_id: i for i in invs}

    @staticmethod
    def get_inventory_item_for_update(product_id, location_id):
        return db.session.query(Inventory).filter_by(
            product_id=product_id,
            location_id=location_id
        ).with_for_update().first()

    @staticmethod
    def get_product_by_id(product_id):
        return Product.query.get(product_id)

    @staticmethod
    def get_products_by_ids(ids):
        ids = [int(p) for p in ids]
        if not ids:
            return {}
        prods = Product.query.filter(Product.id.in_(ids)).all()
        return {p.id: p for p in prods}

    @staticmethod
    def get_product_lots(product_id, location_id):
        """Disponibilidad de lotes por producto y sede.

        Un mismo lote puede llegar en varias partidas con vencimientos distintos
        (ej. 'Demo': 20 uds + 80 uds = 100). La derivación genérica agrupa por
        (lote, vencimiento) y sobrescribe por lote, mostrando solo una partida.
        Aquí se suma TODO el lote (y se muestra el vencimiento más próximo) para
        que el registro y el selector de lotes reflejen la disponibilidad real.
        """
        from app.inventory.services.lot_availability_service import _compute_lot_availability
        avail = _compute_lot_availability(location_id, [product_id])

        entries = []
        for (pid, lot_num), data in avail.items():
            disponible = data['availability']
            if disponible > 0.001:
                entries.append((data['expiration_date'], lot_num, disponible))

        entries.sort(key=lambda e: (e[0] is None, e[0] or date.max))

        lots = [{
            'lot_number': e[1],
            'expiration_date': e[0].strftime('%d/%m/%Y') if e[0] else 'Sin vencimiento',
            'quantity': round(float(e[2]), 2),
        } for e in entries]
        return lots

    @staticmethod
    def get_lots_map(location_id, product_ids):
        """Mapa {product_id: [lotes]} con la misma derivación que get_product_lots
        pero para varios productos a la vez (evita N+1 en tickets multi-línea)."""
        from app.inventory.services.lot_availability_service import _compute_lot_availability
        ids = [int(p) for p in product_ids]
        if not ids:
            return {}
        avail = _compute_lot_availability(int(location_id), ids)
        result = {}
        for (pid, lot_num), data in avail.items():
            disponible = data['availability']
            if disponible <= 0.001:
                continue
            exp = data['expiration_date']
            result.setdefault(pid, []).append({
                'lot_number': lot_num,
                'expiration_date': exp.strftime('%d/%m/%Y') if exp else 'Sin vencimiento',
                'quantity': round(float(disponible), 2),
                '_exp': exp,
            })
        for pid in result:
            result[pid].sort(key=lambda e: (e['_exp'] is None, e['_exp'] or date.max))
            for e in result[pid]:
                e.pop('_exp', None)
        return result

    @staticmethod
    def get_unit_cost(product_id, lot_number):
        try:
            detail = PurchaseDetail.query \
                .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
                .filter(
                    func.upper(Purchase.status) == 'COMPLETED',
                    PurchaseDetail.product_id == int(product_id),
                    PurchaseDetail.lot_number == str(lot_number).strip()
                ) \
                .order_by(PurchaseDetail.id.desc()) \
                .first()
            if detail and detail.foreign_price is not None:
                return Decimal(str(detail.foreign_price))
        except Exception:
            pass
        # Si el lote exacto no aparece en una compra completada (ej. sucursal que
        # recibió por traslado), se usa el último costo de compra del producto.
        try:
            fallback = PurchaseDetail.query \
                .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
                .filter(
                    func.upper(Purchase.status) == 'COMPLETED',
                    PurchaseDetail.product_id == int(product_id)
                ) \
                .order_by(PurchaseDetail.id.desc()) \
                .first()
            if fallback and fallback.foreign_price is not None:
                return Decimal(str(fallback.foreign_price))
        except Exception:
            pass
        return Decimal('0.00')

    @staticmethod
    def get_lot_expiration_date(product_id, lot_number, location_id):
        loc_id = int(location_id)
        prod_id = int(product_id)
        lot = str(lot_number or '').strip()
        if not lot:
            return None
        try:
            if loc_id == 1:
                min_compra = db.session.query(
                    func.min(PurchaseDetail.expiration_date)
                ).join(Purchase, PurchaseDetail.purchase_id == Purchase.id).filter(
                    func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
                    PurchaseDetail.product_id == prod_id,
                    PurchaseDetail.lot_number == lot,
                    PurchaseDetail.expiration_date.isnot(None)
                ).scalar()
                min_devolucion = db.session.query(
                    func.min(MovementDetail.expiration_date)
                ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
                    func.upper(Movement.status).in_(['COMPLETED', 'COMPLETADO']),
                    Movement.destination_location_id == 1,
                    Movement.origin_location_id != 1,
                    MovementDetail.product_id == prod_id,
                    MovementDetail.lot_number == lot,
                    MovementDetail.expiration_date.isnot(None)
                ).scalar()
                exps = [e for e in (min_compra, min_devolucion) if e]
                return min(exps) if exps else None
            else:
                min_exp = db.session.query(
                    func.min(MovementDetail.expiration_date)
                ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
                    func.upper(Movement.status).in_(['COMPLETED', 'COMPLETADO']),
                    Movement.destination_location_id == loc_id,
                    MovementDetail.product_id == prod_id,
                    MovementDetail.lot_number == lot,
                    MovementDetail.expiration_date.isnot(None)
                ).scalar()
                return min_exp
        except Exception:
            return None
        return None

    @staticmethod
    def get_parameter(key, default):
        param = AppParameter.query.filter_by(key=key).first()
        if not param or not param.value:
            return default
        try:
            return float(str(param.value))
        except (TypeError, ValueError, InvalidOperation):
            return default

    @staticmethod
    def get_boolean_parameter(key, default):
        param = AppParameter.query.filter_by(key=key).first()
        if not param or not param.value:
            return default
        normalized = str(param.value).strip().lower()
        if normalized in ('1', 'true', 'yes', 'si', 'on', 'enabled', 'activo'):
            return True
        if normalized in ('0', 'false', 'no', 'off', 'disabled', 'inactivo'):
            return False
        return default

    @staticmethod
    def vencido_permitido_en_central():
        return RegisterWasteRepository.get_boolean_parameter('VENCIDO_PERMITIDO_CENTRAL', True)

    @staticmethod
    def get_time_rule_data(location_id):
        now = current_ve_time()
        since_30 = now - timedelta(days=30)

        normal_records = Waste.query.filter(
            Waste.location_id == location_id,
            Waste.status.in_(['APROBADO']),
            Waste.date >= since_30
        ).all()

        total_normal = sum(float(w.total_quantity or 0) for w in normal_records)

        history_days = 0
        if normal_records:
            oldest = min(w.date for w in normal_records)
            history_days = max(0, (now - oldest).days)

        last_waste = Waste.query.filter(
            Waste.location_id == location_id,
            Waste.status == 'APROBADO',
            Waste.date != None
        ).order_by(Waste.date.desc()).first()

        days_since_last = None
        if last_waste and last_waste.date:
            delta = (now - last_waste.date).days
            days_since_last = max(0, delta)

        return {
            'total_normal': total_normal,
            'days_since_last': days_since_last,
            'history_days': history_days
        }

    @staticmethod
    def deduce_stock_by_lot(inventory_item, lot_number, quantity, previous_stock, new_stock, user_id, waste_id, severity='NORMAL'):
        product_name = inventory_item.product.name if inventory_item.product else f"Insumo #{inventory_item.product_id}"

        changed_data = {
            'waste_id': int(waste_id),
            'product_id': inventory_item.product_id,
            'product_name': product_name,
            'lot_number': str(lot_number or 'N/A'),
            'previous_quantity': float(previous_stock),
            'new_quantity': float(new_stock),
            'quantity_changed': -abs(float(quantity)),
            'notes': 'Registro de merma'
        }

        try:
            user_id_final = int(user_id) if user_id is not None else 1
        except (TypeError, ValueError):
            user_id_final = 1

        audit_entry = AuditLog(
            affected_table='inventory',
            action='MERMA',
            severity=severity,
            user_id=user_id_final,
            location_id=inventory_item.location_id,
            timestamp=current_ve_time(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

    @staticmethod
    def audit_waste_creation(waste, waste_type, user_id, pending, motivos=None):
        # Cada producto se audita con SU PROPIO motivo de merma, no solo con el
        # tipo de la cabecera (que deriva del primer producto).
        productos = []
        for d in (waste.details or []):
            productos.append({
                'product_id': d.product_id,
                'lote': d.lot_number or '',
                'cantidad': float(d.quantity or 0),
                'waste_type_id': d.waste_type_id,
            })

        changed_data = {
            'event': 'creada',
            'waste_id': waste.id,
            'location_id': waste.location_id,
            'waste_type_code': waste_type.code if waste_type else None,
            'waste_type_name': waste_type.name if waste_type else None,
            'total_quantity': float(waste.total_quantity or 0),
            'evidencia': bool(waste.evidence_url),
            'status': waste.status,
            'requiere_aprobacion': pending,
            'motivos': motivos or {},
            'productos': productos,
        }
        try:
            user_id_final = int(user_id) if user_id is not None else 1
        except (TypeError, ValueError):
            user_id_final = 1

        severity = 'ALERTA' if pending else 'NORMAL'

        audit_entry = AuditLog(
            affected_table='waste',
            action='MERMA',
            severity=severity,
            user_id=user_id_final,
            location_id=waste.location_id,
            timestamp=current_ve_time(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

    @staticmethod
    def notify_admins_pending(waste_id, location_id, message):
        from app.models.security_model import Role
        admins = User.query.filter(
            User.role.has(Role.name.in_(['Administrator', 'Admin'])),
            User.is_active == True
        ).all()
        for admin in admins:
            db.session.add(Notification(
                user_id=admin.id,
                location_id=location_id,
                waste_id=waste_id,
                type='MERMA_PENDIENTE',
                message=message[:255],
                is_read=False,
                created_at=current_ve_time(),
            ))

    @staticmethod
    def persist_waste(waste, details, user_id, waste_type, pending, motivos=None):
        db.session.add(waste)
        db.session.flush()

        if not pending:
            for d in details:
                inventory_item = RegisterWasteRepository.get_inventory_item_for_update(
                    d['product_id'], waste.location_id
                )
                if not inventory_item:
                    continue
                stock = float(inventory_item.current_quantity)
                transit = float(inventory_item.transit_quantity or 0)
                reservado = float(inventory_item.reserved_quantity or 0)
                disponible = stock - transit - reservado
                qty = float(d['quantity'])
                if disponible + 1e-9 < qty:
                    name = inventory_item.product.name if inventory_item.product else f"ID {d['product_id']}"
                    raise InsufficientStockError(
                        f"Stock insuficiente para {name}: disponible {disponible:.2f}, "
                        f"solicitado {qty:.2f}."
                    )
                new_stock = stock - qty
                min_stock = float(getattr(inventory_item, 'min_stock', 20))
                if new_stock <= 0.0:
                    severidad = 'CRITICO'
                elif new_stock <= min_stock:
                    severidad = 'ALERTA'
                else:
                    severidad = 'NORMAL'
                inventory_item.current_quantity = new_stock
                RegisterWasteRepository.deduce_stock_by_lot(
                    inventory_item=inventory_item,
                    lot_number=d['lot_number'],
                    quantity=d['quantity'],
                    previous_stock=stock,
                    new_stock=new_stock,
                    user_id=user_id,
                    waste_id=waste.id,
                    severity=severidad,
                )
        else:
            # MERMA PENDIENTE: NO se descuenta el stock físico. Se CONGELA la
            # cantidad en reserved_quantity para que cocina/traslados/ediciones
            # no la consuman hasta que el Admin decida (aprobar/rechazar/cancelar).
            for d in details:
                inventory_item = RegisterWasteRepository.get_inventory_item_for_update(
                    d['product_id'], waste.location_id
                )
                if not inventory_item:
                    continue
                qty = float(d['quantity'])
                inventory_item.reserved_quantity = round(
                    float(inventory_item.reserved_quantity or 0) + qty, 2
                )

        RegisterWasteRepository.audit_waste_creation(
            waste=waste, waste_type=waste_type, user_id=user_id, pending=pending, motivos=motivos
        )

        if pending:
            RegisterWasteRepository.notify_admins_pending(
                waste_id=waste.id,
                location_id=waste.location_id,
                message=f"Merma pendiente de aprobación #{waste.id} ({waste_type.name if waste_type else 'Merma'}).",
            )

        db.session.commit()
        return waste

    @staticmethod
    def get_expired_lots(location_id):
        from app.inventory.services.lot_availability_service import get_expired_lots
        return get_expired_lots(location_id)
