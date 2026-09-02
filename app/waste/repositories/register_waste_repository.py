import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from app.models.inventory_model import db, Inventory, Product
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import Waste, WasteType, WasteDetail, AppParameter, AuditLog
from app.models.security_model import User, Notification, user_locations


class RegisterWasteRepository:

    # =========================================================
    # DATOS DEL FORMULARIO
    # =========================================================
    @staticmethod
    def get_user_by_id(user_id):
        return User.query.get(user_id)

    @staticmethod
    def get_all_sedes():
        # En Mermas la Sede Central (id=1, Almacén) sí es registrable: solo aplican
        # los tipos sensibles (TEMPERATURA, ROBO_SOSPECHA), según la propuesta (3.4,
        # caso de prueba 11). Por eso, a diferencia del Consumo, no se excluye id=1.
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
    def get_product_by_id(product_id):
        return Product.query.get(product_id)

    # =========================================================
    # LOTES POR PRODUCTO + SEDE (reutiliza la derivación existente)
    # =========================================================
    @staticmethod
    def get_product_lots(product_id, location_id):
        from app.inventory.repositories.register_consumption_repository import RegisterConsumptionRepository
        return RegisterConsumptionRepository.get_product_lots(product_id, location_id)

    # =========================================================
    # COSTEO INTERNO (oculto para M9)
    # =========================================================
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
        return Decimal('0.00')

    # =========================================================
    # FECHA DE VENCIMIENTO REAL DEL LOTE
    # (get_product_lots devuelve solo disponibilidad, sin fecha cruda)
    # =========================================================
    @staticmethod
    def get_lot_expiration_date(product_id, lot_number, location_id):
        loc_id = int(location_id)
        prod_id = int(product_id)
        lot = str(lot_number or '').strip()
        if not lot:
            return None
        try:
            if loc_id == 1:
                detail = PurchaseDetail.query \
                    .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
                    .filter(
                        func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
                        PurchaseDetail.product_id == prod_id,
                        PurchaseDetail.lot_number == lot,
                        PurchaseDetail.expiration_date.isnot(None)
                    ) \
                    .order_by(PurchaseDetail.id.desc()) \
                    .first()
                if detail:
                    return detail.expiration_date
            else:
                detail = MovementDetail.query \
                    .join(Movement, MovementDetail.movement_id == Movement.id) \
                    .filter(
                        func.upper(Movement.status).in_(['COMPLETED', 'COMPLETADO']),
                        Movement.destination_location_id == loc_id,
                        MovementDetail.product_id == prod_id,
                        MovementDetail.lot_number == lot,
                        MovementDetail.expiration_date.isnot(None)
                    ) \
                    .order_by(MovementDetail.id.desc()) \
                    .first()
                if detail:
                    return detail.expiration_date
        except Exception:
            return None
        return None

    # =========================================================
    # PARÁMETROS DE TIEMPO (pizarra de reglas)
    # =========================================================
    @staticmethod
    def get_parameter(key, default):
        param = AppParameter.query.filter_by(key=key).first()
        if not param or not param.value:
            return default
        try:
            return float(str(param.value))
        except (TypeError, ValueError, InvalidOperation):
            return default

    # =========================================================
    # REGLA DE TIEMPO: historial normal de la sede y última fecha
    # =========================================================
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

        last_waste = Waste.query.filter(
            Waste.location_id == location_id,
            Waste.date != None
        ).order_by(Waste.date.desc()).first()

        days_since_last = None
        if last_waste and last_waste.date:
            delta = (now - last_waste.date).days
            days_since_last = max(0, delta)

        return {
            'total_normal': total_normal,
            'days_since_last': days_since_last
        }

    # =========================================================
    # PERSISTENCIA: descuento de stock por lote (action='MERMA')
    # =========================================================
    @staticmethod
    def deduce_stock_by_lot(inventory_item, lot_number, quantity, previous_stock, new_stock, user_id, waste_id, severity='NORMAL'):
        product_name = inventory_item.product.name if inventory_item.product else f"Insumo #{inventory_item.product_id}"

        changed_data = json.dumps({
            'waste_id': int(waste_id),
            'product_id': inventory_item.product_id,
            'product_name': product_name,
            'lot_number': str(lot_number or 'N/A'),
            'previous_quantity': float(previous_stock),
            'new_quantity': float(new_stock),
            'quantity_changed': -abs(float(quantity)),
            'notes': 'Registro de merma'
        })

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

    # =========================================================
    # AUDITORÍA DE CABECERA DE MERMA (creación)
    # =========================================================
    @staticmethod
    def audit_waste_creation(waste, waste_type, user_id, pending):
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

    # =========================================================
    # NOTIFICACIÓN a administradores cuando queda PENDIENTE
    # =========================================================
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

    # =========================================================
    # GUARDADO FINAL
    # =========================================================
    @staticmethod
    def persist_waste(waste, details, user_id, waste_type, pending):
        db.session.add(waste)
        db.session.flush()

        inventory_by_key = {}
        for d in details:
            key = (d['product_id'], d['lot_number'])
            if key not in inventory_by_key:
                inventory_by_key[key] = RegisterWasteRepository.get_inventory_item(
                    d['product_id'], waste.location_id
                )

        if not pending:
            for d in details:
                inventory_item = inventory_by_key.get((d['product_id'], d['lot_number']))
                if not inventory_item:
                    continue
                stock = float(inventory_item.current_quantity)
                new_stock = stock - float(d['quantity'])
                min_stock = float(getattr(inventory_item, 'min_stock', 20))
                if new_stock <= 0:
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
            waste=waste, waste_type=waste_type, user_id=user_id, pending=pending
        )

        if pending:
            RegisterWasteRepository.notify_admins_pending(
                waste_id=waste.id,
                location_id=waste.location_id,
                message=f"Merma pendiente de aprobación #{waste.id} ({waste_type.name if waste_type else 'Merma'}).",
            )

        db.session.commit()
        return waste
