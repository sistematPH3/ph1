from decimal import Decimal
from datetime import datetime
from app.models.inventory_model import db
from app.models.waste_model import Waste, WasteDetail
from app.waste.repositories.register_waste_repository import (
    RegisterWasteRepository,
    InsufficientStockError,
)

def get_form_data(user_id):
    user = RegisterWasteRepository.get_user_by_id(user_id)
    if not user:
        return [], False, []

    is_admin = user.role_id == 1

    if is_admin:
        locations = RegisterWasteRepository.get_all_sedes()
    else:
        locations = RegisterWasteRepository.get_user_locations(user_id)

    waste_types = RegisterWasteRepository.get_waste_types()
    return locations, is_admin, waste_types

def user_can_access_location(user_id, location_id):
    if not user_id:
        return False
    try:
        user = RegisterWasteRepository.get_user_by_id(int(user_id))
    except (TypeError, ValueError):
        return False
    if not user:
        return False
    if user.role_id == 1:
        return True
    allowed = [loc.id for loc in RegisterWasteRepository.get_user_locations(int(user_id))]
    return location_id in allowed

def get_location_products(location_id):
    products = RegisterWasteRepository.get_products_in_inventory(location_id)
    return [{'id': p.id, 'name': p.name} for p in products]

def get_product_lots(location_id, product_id):
    return RegisterWasteRepository.get_product_lots(product_id, location_id)

def _evaluate_pending(waste_type, total_quantity, location_id, items):
    """
    Clasificador automático: una merma queda PENDIENTE (merma mayor) si
    cumple CUALQUIERA de estas reglas:
      1) CANTIDAD: total >= límite de merma de CADA producto (waste_limit).
      2) TIPO: el tipo exige aprobación siempre (requires_approval).
      3) TIEMPO: supera lo "esperado" según el historial de la sede.

    Devuelve (pendiente, motivos) donde 'motivos' es un dict por producto
    (product_id -> [códigos]) con las novedades de CADA producto:
    'VENCIDO' (el lote ya pasó su vencimiento), 'LIMITE' (regla de cantidad),
    'TIPO' (el tipo exige aprobación) y 'TIEMPO' (regla temporal). Así la
    auditoría, las respuestas y cualquier bandeja de aprobaciones pueden mostrar
    el motivo por cada producto, incluso varios en el mismo producto
    (p. ej. cadena de frío + límite). La merma queda PENDIENTE con LIMITE/TIPO/
    TIEMPO; el motivo VENCIDO es informativo (el tipo VENCIDO ya validó la
    expiración del lote al registrar).
    """
    motivos = {}

    def marcar(pid, motivo):
        motivos.setdefault(pid, [])
        if motivo not in motivos[pid]:
            motivos[pid].append(motivo)

    por_producto = {}
    for item in items:
        pid = item['product_id']
        por_producto[pid] = por_producto.get(pid, Decimal('0.00')) + Decimal(str(item['quantity']))

    if waste_type and waste_type.code == 'VENCIDO':
        for pid in por_producto:
            marcar(pid, 'VENCIDO')

    cantidad_excede = False
    for pid, total in por_producto.items():
        product = RegisterWasteRepository.get_product_by_id(pid)
        if product and product.waste_limit is not None:
            try:
                if total >= Decimal(str(product.waste_limit)):
                    cantidad_excede = True
                    marcar(pid, 'LIMITE')
            except Exception:
                continue

    if waste_type and waste_type.requires_approval:
        for pid in por_producto:
            marcar(pid, 'TIPO')
        return True, motivos

    if cantidad_excede:
        return True, motivos

    time_data = RegisterWasteRepository.get_time_rule_data(location_id)
    tolerance = RegisterWasteRepository.get_parameter('WASTE_TIME_TOLERANCE', 1.5)
    base_period = RegisterWasteRepository.get_parameter('WASTE_BASE_PERIOD_DAYS', 7)

    if time_data['total_normal'] > 0:
        daily_rate = float(time_data['total_normal']) / 30.0
        elapsed = (time_data['days_since_last']
                   if time_data['days_since_last'] is not None
                   else float(base_period))
        elapsed = max(1.0, float(elapsed))
        expected = daily_rate * elapsed
        threshold = expected * tolerance
        if float(total_quantity) > threshold:
            for pid in por_producto:
                marcar(pid, 'TIEMPO')
            return True, motivos

    return False, motivos

def register_waste(user_id, location_id, waste_type_id, items, evidence_url=None, notes=None):

    if location_id is None:
        return {'success': False, 'message': 'La sede es obligatoria.'}

    waste_type = RegisterWasteRepository.get_waste_type_by_id(waste_type_id)
    if not waste_type or not waste_type.is_active:
        return {'success': False, 'message': 'El tipo de merma seleccionado no es válido.'}

    if int(location_id) == 1 and not waste_type.applies_central:
        vencido_central = RegisterWasteRepository.get_boolean_parameter(
            'VENCIDO_APLICA_CENTRAL', False)
        if not (waste_type.code == 'VENCIDO' and vencido_central):
            return {'success': False, 'message': 'Este tipo de merma no aplica a la Sede Central.'}

    user_row = RegisterWasteRepository.get_user_by_id(user_id)
    if not user_row:
        return {'success': False, 'message': 'No se pudo identificar al usuario.'}

    if not user_can_access_location(user_id, location_id):
        return {'success': False, 'message': 'No tienes permisos para registrar merma en esta sede.'}

    total_quantity = Decimal('0.00')
    total_cost = Decimal('0.00')
    details = []

    try:
        used_by_product = {}
        used_by_lot = {}
        for item in items:
            product_id = int(item['product_id'])
            lot_number = item['lot_number'].strip()
            quantity = Decimal(str(item['quantity']))
            invq = float(quantity)

            inventory_item = RegisterWasteRepository.get_inventory_item(product_id, location_id)
            if not inventory_item:
                return {'success': False, 'message': f'No existe inventario para el producto ID {product_id} en esta sede.'}

            stock = float(inventory_item.current_quantity)
            name = inventory_item.product.name if inventory_item.product else f"ID {product_id}"
            if stock < invq:
                return {'success': False, 'message': f'Stock insuficiente para {name}. Disponible: {stock:.2f}.'}

            acum_producto = used_by_product.get(product_id, 0.0) + invq
            if acum_producto > stock + 1e-9:
                return {
                    'success': False,
                    'message': (
                        f'Stock insuficiente para {name}: se acumulan '
                        f'{acum_producto:.2f} en este ticket (disponible: '
                        f'{stock:.2f}).'
                    )
                }
            used_by_product[product_id] = acum_producto

            available_lots = RegisterWasteRepository.get_product_lots(product_id, location_id)
            matching_lot = next((l for l in available_lots if l['lot_number'] == lot_number), None)
            if not matching_lot or float(matching_lot['quantity']) + 1e-9 < invq:
                lot_disp = float(matching_lot['quantity']) if matching_lot else 0.0
                return {
                    'success': False,
                    'message': (
                        f'El lote {lot_number} de {name} solo dispone de '
                        f'{lot_disp:.2f} unidades (disponible total en la sede: '
                        f'{stock:.2f}). Cantidad solicitada: {quantity}.'
                    )
                }

            saldo_lote = float(matching_lot['quantity'])
            acum_lote = used_by_lot.get((product_id, lot_number), 0.0) + invq
            if acum_lote > saldo_lote + 1e-9:
                return {
                    'success': False,
                    'message': (
                        f'El lote {lot_number} de {name} se solicita acumulado '
                        f'({acum_lote:.2f} unidades en este ticket) y supera su '
                        f'saldo de {saldo_lote:.2f}. Cantidad solicitada: '
                        f'{quantity}.'
                    )
                }
            used_by_lot[(product_id, lot_number)] = acum_lote

            unit_cost = RegisterWasteRepository.get_unit_cost(product_id, lot_number)
            subtotal = (quantity * unit_cost).quantize(Decimal('0.01'))

            expiration_date = RegisterWasteRepository.get_lot_expiration_date(
                product_id, lot_number, location_id
            )

            if waste_type.code == 'VENCIDO':
                if expiration_date is None:
                    return {
                        'success': False,
                        'message': (
                            f'El lote {lot_number} no tiene fecha de '
                            'vencimiento registrada. Con el tipo VENCIDO solo '
                            'se pueden mermar lotes cuya fecha de vencimiento '
                            'ya haya pasado.'
                        )
                    }
                hoy = datetime.now().date()
                vence = expiration_date.date() if hasattr(expiration_date, 'date') else expiration_date
                if vence >= hoy:
                    return {
                        'success': False,
                        'message': (
                            f'El lote {lot_number} vence el '
                            f'{vence.strftime("%d/%m/%Y")}, aún no está vencido. '
                            'Con el tipo VENCIDO solo se pueden mermar lotes '
                            'cuya fecha de vencimiento ya haya pasado.'
                        )
                    }

            details.append({
                'product_id': product_id,
                'product_name': name,
                'lot_number': lot_number,
                'expiration_date': expiration_date,
                'quantity': quantity,
                'unit_cost': unit_cost,
                'subtotal_cost': subtotal,
            })
            total_quantity += quantity
            total_cost += subtotal

        pending, motivos = _evaluate_pending(waste_type, total_quantity, location_id, items)

        waste = Waste(
            location_id=location_id,
            waste_type_id=waste_type.id,
            evidence_url=evidence_url or None,
            notes=(notes or '').strip() or None,
            date=datetime.utcnow(),
            user_id=user_id,
            status='PENDIENTE' if pending else 'APROBADO',
            total_quantity=total_quantity.quantize(Decimal('0.01')),
            total_cost=total_cost.quantize(Decimal('0.01')),
            currency='USD',
        )

        for d in details:
            waste.details.append(WasteDetail(
                product_id=d['product_id'],
                lot_number=d['lot_number'],
                expiration_date=d['expiration_date'],
                quantity=d['quantity'],
                unit_cost=d['unit_cost'],
                subtotal_cost=d['subtotal_cost'],
            ))

        RegisterWasteRepository.persist_waste(
            waste=waste,
            details=details,
            user_id=user_id,
            waste_type=waste_type,
            pending=pending,
            motivos=motivos,
        )

        novedades = {}
        for pid, cods in motivos.items():
            nombre = next(
                (d['product_name'] for d in details if d['product_id'] == pid),
                f"ID {pid}"
            )
            novedades[str(pid)] = {'name': nombre, 'motivos': cods}

        return {
            'success': True,
            'waste_id': waste.id,
            'status': waste.status,
            'novedades': novedades,
            'message': (
                'Merma registrada exitosamente. Quedó PENDIENTE de aprobación y se notificó al administrador.'
                if pending else
                'Merma registrada exitosamente y el stock fue descontado.'
            ),
        }

    except InsufficientStockError as e:
        db.session.rollback()
        return {'success': False, 'message': str(e)}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'Error interno del servidor: {str(e)}'}
