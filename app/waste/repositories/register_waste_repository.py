import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import Waste, WasteType, WasteDetail, AppParameter, AuditLog
from app.models.security_model import User, Notification, user_locations

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
    def get_inventory_item_for_update(product_id, location_id):
        return db.session.query(Inventory).filter_by(
            product_id=product_id,
            location_id=location_id
        ).with_for_update().first()

    @staticmethod
    def get_product_by_id(product_id):
        return Product.query.get(product_id)

    @staticmethod
    def _compute_lot_availability(loc_id, prod_ids):
        """Disponibilidad por (producto, lote) en una sede, para varios productos.

        Replica la derivación de get_product_lots en una sola pasada (evita N+1):
        una consulta por conjunto de (entradas, salidas por traslado, consumos,
        mermas aprobadas). Los consumos sin lote ('N/A') se descuentan de los
        lotes del producto por orden de vencimiento (FIFO, vencidos primero).
        """
        loc_id = int(loc_id)
        prod_ids = [int(p) for p in prod_ids]
        if not prod_ids:
            return {}

        moved_statuses = ['COMPLETED', 'COMPLETADO', 'NOVEDAD_FALTANTE',
                          'CERRADO_POR_ADMIN', 'CERRADO_CON_PERDIDA']

        entradas = {}

        if loc_id == 1:
            compras = db.session.query(
                PurchaseDetail.product_id,
                PurchaseDetail.lot_number,
                func.min(PurchaseDetail.expiration_date).label('min_exp'),
                func.sum(PurchaseDetail.quantity).label('total_qty')
            ).join(Purchase, PurchaseDetail.purchase_id == Purchase.id).filter(
                func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
                PurchaseDetail.product_id.in_(prod_ids),
                PurchaseDetail.lot_number.isnot(None),
                PurchaseDetail.lot_number != ''
            ).group_by(PurchaseDetail.product_id, PurchaseDetail.lot_number).all()

            devoluciones = db.session.query(
                MovementDetail.product_id,
                MovementDetail.lot_number,
                func.min(MovementDetail.expiration_date).label('min_exp'),
                func.sum(func.coalesce(MovementDetail.received_quantity,
                                       MovementDetail.quantity)).label('total_qty')
            ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
                func.upper(Movement.status).in_(moved_statuses),
                Movement.destination_location_id == 1,
                Movement.origin_location_id != 1,
                MovementDetail.product_id.in_(prod_ids),
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(MovementDetail.product_id, MovementDetail.lot_number).all()

            for pid, lot, min_exp, total_qty in list(compras) + list(devoluciones):
                key = (int(pid), lot.strip())
                prev = entradas.get(key)
                exps = [e for e in (prev['expiration_date'] if prev else None, min_exp) if e]
                entradas[key] = {
                    'expiration_date': min(exps) if exps else None,
                    'total_in': float(total_qty or 0.0) + (prev['total_in'] if prev else 0.0),
                }
        else:
            entradas_rows = db.session.query(
                MovementDetail.product_id,
                MovementDetail.lot_number,
                func.min(MovementDetail.expiration_date).label('min_exp'),
                func.sum(func.coalesce(MovementDetail.received_quantity,
                                       MovementDetail.quantity)).label('total_qty')
            ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
                func.upper(Movement.status).in_(moved_statuses),
                Movement.destination_location_id == loc_id,
                MovementDetail.product_id.in_(prod_ids),
                MovementDetail.lot_number.isnot(None),
                MovementDetail.lot_number != ''
            ).group_by(MovementDetail.product_id, MovementDetail.lot_number).all()
            for pid, lot, min_exp, total_qty in entradas_rows:
                key = (int(pid), lot.strip())
                entradas[key] = {
                    'expiration_date': min_exp,
                    'total_in': float(total_qty or 0.0),
                }

        salidas_traslados = {}
        salidas_rows = db.session.query(
            MovementDetail.product_id,
            MovementDetail.lot_number,
            func.sum(MovementDetail.quantity).label('total_out')
        ).join(Movement, MovementDetail.movement_id == Movement.id).filter(
            Movement.origin_location_id == loc_id,
            Movement.status.notin_(['ANULADO', 'CANCELADO', 'RECHAZADO', 'CANCELADO_EMISOR']),
            MovementDetail.product_id.in_(prod_ids),
            MovementDetail.lot_number.isnot(None)
        ).group_by(MovementDetail.product_id, MovementDetail.lot_number).all()
        for pid, lot, total_out in salidas_rows:
            if lot:
                salidas_traslados[(int(pid), lot.strip())] = float(total_out or 0.0)

        salidas_consumo = {}
        audit_records = db.session.query(AuditLog.changed_data).filter(
            AuditLog.location_id == loc_id,
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA'])
        ).all()
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
            try:
                p_id = int(c_data.get('product_id')) if c_data.get('product_id') is not None else None
            except (TypeError, ValueError):
                p_id = None
            if p_id not in prod_ids:
                continue
            l_num = c_data.get('lot_number')
            try:
                qty_change = float(c_data.get('quantity_changed', 0.0))
            except (TypeError, ValueError):
                qty_change = 0.0
            l_clean = str(l_num).strip() if l_num else 'N/A'
            key = (p_id, l_clean)
            salidas_consumo[key] = salidas_consumo.get(key, 0.0) + abs(qty_change)

        salidas_aprobadas = {}
        aprobadas_rows = db.session.query(
            WasteDetail.product_id,
            WasteDetail.lot_number,
            func.sum(WasteDetail.quantity).label('total_mermado')
        ).join(Waste, Waste.id == WasteDetail.waste_id).filter(
            Waste.status == 'APROBADO',
            Waste.cancelled_at.is_(None),
            Waste.location_id == loc_id,
            WasteDetail.product_id.in_(prod_ids),
            WasteDetail.lot_number.isnot(None),
        ).group_by(WasteDetail.product_id, WasteDetail.lot_number).all()
        for pid, lot, total_mermado in aprobadas_rows:
            if lot and str(lot).strip() and str(lot).strip() != 'N/A':
                salidas_aprobadas[(int(pid), str(lot).strip())] = float(total_mermado or 0.0)

        por_producto = {}
        result = {}
        for key, data in entradas.items():
            pid, lot = key
            disp = (data['total_in']
                    - salidas_traslados.get(key, 0.0)
                    - salidas_consumo.get(key, 0.0)
                    - salidas_aprobadas.get(key, 0.0))
            result[key] = {
                'availability': disp,
                'expiration_date': data['expiration_date'],
            }
            por_producto.setdefault(pid, []).append((lot, result[key]))

        # Consumos registrados sin lote ('N/A'): se descuentan de los lotes del
        # producto por orden de vencimiento (FIFO, vencidos primero).
        for (pid, l_num), total_na in salidas_consumo.items():
            if l_num != 'N/A':
                continue
            if total_na <= 0:
                continue
            lots = sorted(
                por_producto.get(pid, []),
                key=lambda kv: (kv[1]['expiration_date'] is None, kv[1]['expiration_date'])
            )
            pendiente = total_na
            for lot, ldata in lots:
                if pendiente <= 0:
                    break
                if ldata['availability'] <= 0.001:
                    continue
                usar = min(pendiente, ldata['availability'])
                ldata['availability'] -= usar
                pendiente -= usar

        return result

    @staticmethod
    def get_product_lots(product_id, location_id):
        """Disponibilidad de lotes por producto y sede.

        Un mismo lote puede llegar en varias partidas con vencimientos distintos
        (ej. 'Demo': 20 uds + 80 uds = 100). La derivación genérica agrupa por
        (lote, vencimiento) y sobrescribe por lote, mostrando solo una partida.
        Aquí se suma TODO el lote (y se muestra el vencimiento más próximo) para
        que el registro y el selector de lotes reflejen la disponibilidad real.
        """
        avail = RegisterWasteRepository._compute_lot_availability(location_id, [product_id])

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
        return True

    @staticmethod
    def get_time_rule_data(location_id):
        now = datetime.utcnow()
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
            Waste.status.in_(['APROBADO', 'REVERTIDO']),
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
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

    @staticmethod
    def audit_waste_creation(waste, waste_type, user_id, pending, motivos=None):
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
            timestamp=datetime.now(),
            changed_data=changed_data
        )
        db.session.add(audit_entry)

    @staticmethod
    def notify_admins_pending(waste_id, location_id, message):
        admins = User.query.filter(
            User.role.has(name='Administrator'),
            User.is_active == True
        ).all()
        for admin in admins:
            db.session.add(Notification(
                user_id=admin.id,
                location_id=location_id,
                type='MERMA_PENDIENTE',
                message=message[:255],
                is_read=False,
                created_at=datetime.utcnow(),
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
                qty = float(d['quantity'])
                if stock + 1e-9 < qty:
                    name = inventory_item.product.name if inventory_item.product else f"ID {d['product_id']}"
                    raise InsufficientStockError(
                        f"Stock insuficiente para {name}: disponible {stock:.2f}, "
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
        loc_id = int(location_id)
        today = datetime.now().date()
        products = RegisterWasteRepository.get_products_in_inventory(loc_id)
        if not products:
            return []

        prod_ids = [p.id for p in products]
        name_by_id = {p.id: p.name for p in products}
        avail = RegisterWasteRepository._compute_lot_availability(loc_id, prod_ids)

        vencidos = []
        for (pid, lot_num), data in avail.items():
            exp = data['expiration_date']
            if exp is None:
                continue
            exp_date = exp.date() if hasattr(exp, 'date') else exp
            if exp_date >= today:
                continue
            disponible = data['availability']
            if disponible <= 0.001:
                continue
            vencidos.append({
                'product_id': pid,
                'product_name': name_by_id.get(pid, f"ID {pid}"),
                'lot_number': lot_num,
                'quantity': round(float(disponible), 2),
                'expiration_date': exp_date.strftime('%d/%m/%Y'),
            })
        vencidos.sort(key=lambda v: (v['expiration_date'], v['product_name'], v['lot_number']))
        return vencidos
