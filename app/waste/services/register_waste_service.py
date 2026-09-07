from decimal import Decimal
from datetime import datetime
import math
from app.models.inventory_model import db
from app.models.waste_model import Waste, WasteDetail, WasteDetailPhoto
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
      3) TIEMPO: supera lo "esperado" según el historial de la sede, una vez
         que la sede acumuló el período base de días de registros.

    Devuelve (pendiente, motivos) donde 'motivos' es un dict por producto
    (product_id -> [códigos]) con las novedades de CADA producto:
    'VENCIDO' (un lote ya pasó su vencimiento), 'LIMITE' (regla de cantidad),
    'TIPO' (el tipo exige aprobación) y 'TIEMPO' (regla temporal). Así la
    auditoría, las respuestas y cualquier bandeja de aprobaciones pueden mostrar
    el motivo por cada producto, incluso varios en el mismo producto
    (p. ej. cadena de frío + límite). La merma queda PENDIENTE con LIMITE/TIPO/
    TIEMPO; el motivo VENCIDO es informativo (el tipo VENCIDO ya validó la
    expiración del lote al registrar).

    Cada ÍTEM puede traer su PROPIO tipo de merma (item['_waste_type']) para
    soportar tickets con motivos distintos por producto. Si un ítem no lo trae,
    hereda el tipo de la cabecera (waste_type).
    """
    motivos = {}

    def marcar(pid, motivo):
        motivos.setdefault(pid, [])
        if motivo not in motivos[pid]:
            motivos[pid].append(motivo)

    por_producto = {}
    tipos_por_producto = {}
    for item in items:
        pid = item['product_id']
        por_producto[pid] = por_producto.get(pid, Decimal('0.00')) + Decimal(str(item['quantity']))
        t = item.get('_waste_type') or waste_type
        tipos_por_producto.setdefault(pid, []).append(t)

    for pid, tipos in tipos_por_producto.items():
        if any(getattr(t, 'code', None) == 'VENCIDO' for t in tipos):
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

    # Soporte por ítem: aunque la cabecera no exija aprobación, un producto
    # puede tener un tipo propio que sí la exija (p. ej. TEMPERATURA).
    if any(getattr(t, 'requires_approval', False)
           for tipos in tipos_por_producto.values() for t in tipos):
        for pid, tipos in tipos_por_producto.items():
            if any(getattr(t, 'requires_approval', False) for t in tipos):
                marcar(pid, 'TIPO')
        return True, motivos

    if cantidad_excede:
        return True, motivos

    time_data = RegisterWasteRepository.get_time_rule_data(location_id)
    tolerance = RegisterWasteRepository.get_parameter('WASTE_TIME_TOLERANCE', 1.5)
    base_period = max(1.0, float(
        RegisterWasteRepository.get_parameter('WASTE_BASE_PERIOD_DAYS', 7)))

    if (time_data['total_normal'] > 0
            and time_data.get('history_days', 0) >= base_period):
        daily_rate = float(time_data['total_normal']) / 30.0
        elapsed = (time_data['days_since_last']
                   if time_data['days_since_last'] is not None
                   else base_period)
        elapsed = max(1.0, float(elapsed))
        expected = daily_rate * elapsed
        threshold = expected * tolerance
        if float(total_quantity) > threshold:
            for pid in por_producto:
                marcar(pid, 'TIEMPO')
            return True, motivos

    return False, motivos

def register_waste(user_id, location_id, waste_type_id, items, evidence_url=None, notes=None, request_id=None):
    request_id = (request_id or '').strip() or None
    if request_id:
        existing = RegisterWasteRepository.get_waste_by_request_id(request_id)
        if existing:
            return {
                'success': True,
                'waste_id': existing.id,
                'status': existing.status,
                'duplicate': True,
                'message': (
                    'Ya existe una merma registrada con este identificador de '
                    'solicitud. No se creó un registro duplicado.'
                ),
            }

    if location_id is None:
        return {'success': False, 'message': 'La sede es obligatoria.'}

    waste_type = RegisterWasteRepository.get_waste_type_by_id(waste_type_id)
    if not waste_type or not waste_type.is_active:
        return {'success': False, 'message': 'El tipo de merma seleccionado no es válido.'}

    if int(location_id) == 1 and not waste_type.applies_central \
            and waste_type.code != 'VENCIDO':
        return {'success': False, 'message': 'Este tipo de merma no aplica a la Sede Central.'}

    # Cada ítem puede llevar SU PROPIO tipo de merma. Sin él, hereda el de la
    # cabecera. Resolvemos y validamos aquí para usarlo en el bucle de líneas.
    for item in items:
        item_type_id = item.get('waste_type_id')
        if item_type_id in (None, ''):
            item['_waste_type'] = waste_type
            continue
        item_type = RegisterWasteRepository.get_waste_type_by_id(int(item_type_id))
        if not item_type or not item_type.is_active:
            return {
                'success': False,
                'message': 'El tipo de merma elegido para uno de los productos no es válido.'
            }
        if int(location_id) == 1 and not item_type.applies_central \
                and item_type.code != 'VENCIDO':
            return {
                'success': False,
                'message': (
                    f'El tipo de merma "{item_type.name}" de uno de los '
                    'productos no aplica a la Sede Central.'
                )
            }
        item['_waste_type'] = item_type

    user_row = RegisterWasteRepository.get_user_by_id(user_id)
    if not user_row:
        return {'success': False, 'message': 'No se pudo identificar al usuario.'}

    if not user_can_access_location(user_id, location_id):
        return {'success': False, 'message': 'No tienes permisos para registrar merma en esta sede.'}

    for item in items:
        try:
            q = item.get('quantity')
            if isinstance(q, bool) or q is None or not isinstance(q, (int, float)):
                raise ValueError
            fq = float(q)
            if not math.isfinite(fq) or fq <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return {
                'success': False,
                'message': 'Cantidad inválida en uno de los productos (debe ser mayor a 0).'
            }

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
            transit = float(inventory_item.transit_quantity or 0)
            reservado = float(inventory_item.reserved_quantity or 0)
            disponible = stock - transit - reservado
            name = inventory_item.product.name if inventory_item.product else f"ID {product_id}"
            if disponible < invq:
                return {'success': False, 'message': f'Stock insuficiente para {name}. Disponible: {disponible:.2f}.'}

            acum_producto = used_by_product.get(product_id, 0.0) + invq
            if acum_producto > disponible + 1e-9:
                return {
                    'success': False,
                    'message': (
                        f'Stock insuficiente para {name}: se acumulan '
                        f'{acum_producto:.2f} en este ticket (disponible: '
                        f'{disponible:.2f}).'
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
                        f'{disponible:.2f}). Cantidad solicitada: {quantity}.'
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

            item_type = item.get('_waste_type') or waste_type
            if item_type.code == 'VENCIDO':
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

            ev_raw = item.get('evidence_urls') or []
            ev_urls = []
            seen = set()
            for u in ev_raw:
                if isinstance(u, str) and u.strip() and u.strip() not in seen:
                    seen.add(u.strip())
                    ev_urls.append(u.strip())
            fallback = (item.get('evidence_url') or '').strip() or None
            first_evidence = ev_urls[0] if ev_urls else fallback

            details.append({
                'product_id': product_id,
                'product_name': name,
                'lot_number': lot_number,
                'expiration_date': expiration_date,
                'quantity': quantity,
                'unit_cost': unit_cost,
                'subtotal_cost': subtotal,
                'waste_type_id': item_type.id,
                'evidence_url': first_evidence,
                'evidence_urls': ev_urls,
            })
            total_quantity += quantity
            total_cost += subtotal

        pending, motivos = _evaluate_pending(waste_type, total_quantity, location_id, items)

        waste = Waste(
            location_id=location_id,
            waste_type_id=waste_type.id,
            evidence_url=evidence_url or None,
            notes=(notes or '').strip() or None,
            request_id=request_id,
            date=datetime.utcnow(),
            user_id=user_id,
            status='PENDIENTE' if pending else 'APROBADO',
            total_quantity=total_quantity.quantize(Decimal('0.01')),
            total_cost=total_cost.quantize(Decimal('0.01')),
            currency='USD',
        )

        for d in details:
            wd = WasteDetail(
                product_id=d['product_id'],
                lot_number=d['lot_number'],
                expiration_date=d['expiration_date'],
                quantity=d['quantity'],
                unit_cost=d['unit_cost'],
                subtotal_cost=d['subtotal_cost'],
                waste_type_id=d.get('waste_type_id'),
                evidence_url=d['evidence_url'],
            )
            for pos, p_url in enumerate(d['evidence_urls'], start=1):
                wd.photos.append(WasteDetailPhoto(photo_url=p_url, position=pos))
            waste.details.append(wd)

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