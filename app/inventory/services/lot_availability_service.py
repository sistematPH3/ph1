"""Servicio compartido de disponibilidad de lotes (Módulo 8 - Familia B: Vencidos).

Extraído de register_waste_repository.py para ser la FUENTE ÚNICA de cálculo
de vencidos. Lo usan: Dashboard (cuadro vencidos), formulario de mermas
(GET /waste/merma/new), deep link (GET /waste/merma/new?origin=alarma_vencido).
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import func, or_

from app.extensions import db
from app.models.logistics_model import Location, Purchase, PurchaseDetail, Movement, MovementDetail
from app.models.waste_model import Waste, WasteDetail, WasteType, AuditLog
from app.models.security_model import User
from app.time_utils import current_ve_time


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
        or_(
            Waste.status == 'APROBADO',
            (Waste.status == 'APROBADO_PARCIAL') & (WasteDetail.status == 'APROBADO'),
        ),
        Waste.cancelled_at.is_(None),
        Waste.location_id == loc_id,
        WasteDetail.product_id.in_(prod_ids),
        WasteDetail.lot_number.isnot(None),
    ).group_by(WasteDetail.product_id, WasteDetail.lot_number).all()
    for pid, lot, total_mermado in aprobadas_rows:
        if lot and str(lot).strip() and str(lot).strip() != 'N/A':
            salidas_aprobadas[(int(pid), str(lot).strip())] = float(total_mermado or 0.0)

    # Mermas PENDIENTES (en proceso): el stock físico no se descuenta todavía,
    # pero la cantidad ya está comprometida. Se resta de la disponibilidad del
    # lote para que la suma de mermas (pendientes + nuevas) jamás supere el
    # inventario físico. En APROBADO_PARCIAL, las líneas aún sin decidir
    # también se restan (las RECHAZADAS no comprometen stock).
    salidas_pendientes = {}
    pendientes_rows = db.session.query(
        WasteDetail.product_id,
        WasteDetail.lot_number,
        func.sum(WasteDetail.quantity).label('total_pend')
    ).join(Waste, Waste.id == WasteDetail.waste_id).filter(
        or_(
            Waste.status == 'PENDIENTE',
            (Waste.status == 'APROBADO_PARCIAL') & (WasteDetail.status != 'APROBADO'),
        ),
        Waste.cancelled_at.is_(None),
        Waste.location_id == loc_id,
        WasteDetail.product_id.in_(prod_ids),
        WasteDetail.lot_number.isnot(None),
    ).group_by(WasteDetail.product_id, WasteDetail.lot_number).all()
    for pid, lot, total_pend in pendientes_rows:
        if lot and str(lot).strip() and str(lot).strip() != 'N/A':
            salidas_pendientes[(int(pid), str(lot).strip())] = float(total_pend or 0.0)

    por_producto = {}
    result = {}
    for key, data in entradas.items():
        pid, lot = key
        disp = (data['total_in']
                - salidas_traslados.get(key, 0.0)
                - salidas_consumo.get(key, 0.0)
                - salidas_aprobadas.get(key, 0.0)
                - salidas_pendientes.get(key, 0.0))
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


def get_expired_lots(location_id):
    """Lotes vencidos con saldo disponible en una sede."""
    loc_id = int(location_id)
    today = current_ve_time().date()
    from app.waste.repositories.register_waste_repository import RegisterWasteRepository
    products = RegisterWasteRepository.get_products_in_inventory(loc_id)
    if not products:
        return []

    prod_ids = [p.id for p in products]
    name_by_id = {p.id: p.name for p in products}
    avail = _compute_lot_availability(loc_id, prod_ids)

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
            '_exp_date_obj': exp_date,  # Keep date object for sorting
        })
    # Sort by actual date object, not string
    vencidos.sort(key=lambda v: (v['_exp_date_obj'], v['product_name'], v['lot_number']))
    # Remove the temporary sort key
    for v in vencidos:
        v.pop('_exp_date_obj', None)
    return vencidos


def obtener_vencidos_para_dashboard(user):
    """Vencidos por sede para el usuario actual (Dashboard).

    - Admin: ve todas las sedes activas
    - Otros roles operativos: solo sus sedes asignadas
    - Finance: NO ve vencidos (no registra mermas)
    - Respeta `vencido_permitido_en_central()` para la Sede Central (id=1)
    """
    from app.waste.repositories.register_waste_repository import RegisterWasteRepository

    # Verificar rol usando el usuario pasado como parámetro
    is_admin = getattr(user, 'is_admin', False)
    is_finance = getattr(user, 'is_finance', False)

    if is_finance:
        return []

    # Obtener sedes del usuario
    if is_admin:
        sedes = Location.query.filter_by(is_active=True).all()
    else:
        user_locs = getattr(user, 'locations', [])
        sedes = [loc for loc in user_locs if loc.is_active]

    if not sedes:
        return []

    resultado = []
    for sede in sedes:
        # Saltar Central si no permite vencidos
        if sede.id == 1 and not RegisterWasteRepository.vencido_permitido_en_central():
            continue
        vencidos = get_expired_lots(sede.id)
        if not vencidos:
            continue
        for v in vencidos:
            v['location_id'] = sede.id
            v['location_name'] = sede.name
        resultado.extend(vencidos)

    from datetime import datetime
    resultado.sort(key=lambda v: (datetime.strptime(v['expiration_date'], '%d/%m/%Y'), v['product_name'], v['lot_number']))
    return resultado