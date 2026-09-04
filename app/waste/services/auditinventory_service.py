from app.waste.repositories.auditinventory_repository import AuditInventoryRepository
from app.models import Location, Movement, PurchaseAuditLog, Product, WasteDetail
from datetime import datetime, timezone
from decimal import Decimal
import json
import re

def get_audit_view_data(user_id):
    user = AuditInventoryRepository.get_user_by_id(user_id)
    if not user:
        return [], False, None

    is_admin = (user.role_id == 1)
    
    if is_admin:
        locations = AuditInventoryRepository.get_all_locations()
    else:
        allowed_ids = AuditInventoryRepository.get_user_allowed_locations(user_id)
        locations = [loc for loc in AuditInventoryRepository.get_all_locations() if loc.id in allowed_ids]

    return locations, is_admin, user

def fetch_filtered_audit_logs(user, is_admin, filters):
    allowed_locations = None
    
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return [] 

    location_id_filter = filters.get('location_id')
    severity_filter = filters.get('severity')

    if location_id_filter:
        location_id_filter = int(location_id_filter)

    severity_filter = severity_filter.upper() if severity_filter else None

    if not is_admin and location_id_filter:
        if location_id_filter not in allowed_locations:
            return []

    raw_logs = AuditInventoryRepository.get_audit_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        severity_filter=severity_filter
    )
    
    annulled_target_ids = set()
    sorted_logs = sorted(raw_logs, key=lambda x: x.id) 
    
    for log in sorted_logs:
        act_upper = (log.action or '').upper()
        c_data = log.changed_data or {}
        if isinstance(c_data, str):
            try: 
                c_data = json.loads(c_data)
            except json.JSONDecodeError: 
                c_data = {}
        
        notes = c_data.get('notes', '')
        match = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
        
        if match:
            target_id = int(match.group(1))
            if 'REVERSION' in act_upper:
                annulled_target_ids.add(target_id)
            elif 'ACTIVACION' in act_upper or 'REACTIVACION' in act_upper:
                annulled_target_ids.discard(target_id)

    formatted_logs = []
    for log in raw_logs:
        changed_data = log.changed_data or {}
        if isinstance(changed_data, str):
            try:
                changed_data = json.loads(changed_data)
            except json.JSONDecodeError:
                changed_data = {}
        
        qty_changed = float(changed_data.get('quantity_changed', 0))
        
        def safe_float(val):
            if val in (None, ''):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        prev_qty = safe_float(changed_data.get('previous_quantity'))
        new_qty = safe_float(changed_data.get('new_quantity'))

        if qty_changed != 0:
            if qty_changed < 0:
                if prev_qty in (0, 0.0, None):
                    if new_qty is not None and new_qty > 0:
                        prev_qty = new_qty - qty_changed
                    else:
                        prev_qty = abs(qty_changed)
                        new_qty = 0.0
                elif new_qty is None:
                    new_qty = prev_qty + qty_changed

            elif qty_changed > 0:
                if prev_qty in (0, 0.0, None) and new_qty in (0, 0.0, None):
                    prev_qty = 0.0
                    new_qty = qty_changed
                elif new_qty is None and prev_qty is not None:
                    new_qty = prev_qty + qty_changed
                elif prev_qty is None and new_qty is not None:
                    prev_qty = new_qty - qty_changed

        if prev_qty is None: prev_qty = 0.0
        if new_qty is None: new_qty = 0.0

        if prev_qty < 0: prev_qty = 0.0
        if new_qty < 0: new_qty = 0.0

        act_upper = (log.action or '').upper()
        is_adjustment_type = any(kw in act_upper for kw in ['REVERSION', 'AJUSTE', 'ACTIVACION'])
        is_annulled = (log.id in annulled_target_ids)

        formatted_logs.append({
            'id': log.id,
            'action': log.action,
            'severity': log.severity,
            'user_name': log.user_name,
            'location_name': log.location_name or changed_data.get('location_name', 'Almacén Principal'),
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else 'N/A',
            'product_name': changed_data.get('product_name') or changed_data.get('producto') or changed_data.get('nombre') or 'N/A',
            'previous_quantity': prev_qty,
            'new_quantity': new_qty,
            'quantity_changed': qty_changed,
            'notes': changed_data.get('notes', ''),
            'is_annulled': is_annulled,
            'is_adjustment_type': is_adjustment_type
        })
        
    return formatted_logs

def process_inventory_action(log_id, current_user, action_type, new_quantity_requested=None, justification_notes="", lot_number=None):
    original_log_tuple = AuditInventoryRepository.get_audit_log_by_id(log_id)
    if not original_log_tuple:
        return {'success': False, 'message': 'El registro de auditoría solicitado no existe.'}
    
    location_id = original_log_tuple.location_id
    action_name_upper = original_log_tuple.action.upper()

    # Las mermas son un registro contable irrevocable: no se editan, anulan ni reactivan.
    if 'MERMA' in action_name_upper:
        return {'success': False, 'message': 'Operación denegada. Una merma no se puede editar, anular ni activar.'}

    if location_id == 1 or "COMPRA" in action_name_upper or "INGRESO" in action_name_upper:
        return {'success': False, 'message': 'Operación denegada. Las compras o registros en el Almacén General no admiten modificaciones.'}

    is_admin = (current_user.role_id == 1)
    is_finance = (current_user.role_id == 6)

    if is_finance:
        return {'success': False, 'message': 'Operación denegada. El perfil de finanzas posee atributos de solo lectura.'}

    log_timestamp = original_log_tuple.timestamp
    if log_timestamp.tzinfo is None:
        log_timestamp = log_timestamp.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    diff_hours = (now - log_timestamp).total_seconds() / 3600

    if not is_admin:
        if diff_hours > 24:
            return {'success': False, 'message': 'El tiempo límite de 24 horas ha expirado. Solicite la acción al Administrador.'}
    else:
        if diff_hours > (30 * 24):
            return {'success': False, 'message': 'El límite máximo de 30 días permitido para administradores ha expirado.'}

    changed_data = original_log_tuple.changed_data
    if isinstance(changed_data, str):
        try:
            changed_data = json.loads(changed_data)
        except json.JSONDecodeError:
            changed_data = {}
    elif not changed_data:
        changed_data = {}

    product_id = (
        changed_data.get('product_id') or 
        changed_data.get('insumo_id') or 
        changed_data.get('id_producto') or 
        changed_data.get('id_insumo') or 
        changed_data.get('item_id') or 
        changed_data.get('id')
    )
    product_name = changed_data.get('product_name') or changed_data.get('producto') or changed_data.get('nombre') or 'Insumo no especificado'

    if not product_id and product_name != 'Insumo no especificado':
        try:
            from app.models.inventory_model import db
            from sqlalchemy import text
            res = db.session.execute(text("SELECT id FROM products WHERE LOWER(name) = LOWER(:pname) LIMIT 1"), {'pname': str(product_name).strip()}).fetchone()
            if res:
                product_id = res[0]
            else:
                res_ins = db.session.execute(text("SELECT id FROM insumos WHERE LOWER(nombre) = LOWER(:pname) LIMIT 1"), {'pname': str(product_name).strip()}).fetchone()
                if res_ins:
                    product_id = res_ins[0]
        except Exception:
            pass

    if not product_id:
        return {'success': False, 'message': 'El registro carece del identificador de insumo necesario para procesar la acción.'}

    original_qty_changed = Decimal(str(
        changed_data.get('quantity_changed') or 
        changed_data.get('new_quantity') or 
        changed_data.get('cantidad') or 0
    ))
    
    if original_qty_changed == 0:
        p_qty = changed_data.get('previous_quantity')
        n_qty = changed_data.get('new_quantity')
        if p_qty is not None and n_qty is not None:
            original_qty_changed = Decimal(str(n_qty)) - Decimal(str(p_qty))

    current_stock = AuditInventoryRepository.get_current_stock(location_id, product_id)
    current_stock = Decimal('0.00') if current_stock is None else Decimal(str(current_stock))

    new_severity_status = None

    if action_type == 'ANULAR':
        required_adjustment = -original_qty_changed
        final_action = f"REVERSION_{original_log_tuple.action}"
        final_notes = f"Anulación del log #{log_id}. Motivo: {justification_notes}"
        new_severity_status = 'ANULADO'

    elif action_type == 'ACTIVAR':
        required_adjustment = original_qty_changed
        final_action = f"ACTIVACION_{original_log_tuple.action}"
        final_notes = f"Reactivación del log #{log_id}. Motivo: {justification_notes}"
        new_severity_status = 'NORMAL'

    elif action_type == 'EDITAR':
        if new_quantity_requested is None:
            return {'success': False, 'message': 'Debe especificar la nueva cantidad para procesar la edición.'}
        
        new_requested_dec = Decimal(str(new_quantity_requested))
        abs_original = abs(original_qty_changed)

        is_consumption = (
            "GASTO" in action_name_upper or 
            "CONSUMO" in action_name_upper or 
            "MERMA" in action_name_upper or 
            original_qty_changed < 0
        )

        if is_consumption:
            abs_new = abs(new_requested_dec)
            required_adjustment = abs_original - abs_new
        else:
            required_adjustment = new_requested_dec - original_qty_changed

        final_action = f"AJUSTE_{original_log_tuple.action}"
        base_notes = f"Edición del log #{log_id}"
        if is_consumption:
            final_notes = (
                f"{base_notes}: cantidad corregida de {abs_original:.2f} a {abs_new:.2f} unidades."
                f" Motivo: {justification_notes}"
            )
        else:
            final_notes = (
                f"{base_notes}: nueva variación de {original_qty_changed:.2f} a {new_requested_dec:.2f}."
                f" Motivo: {justification_notes}"
            )
        if lot_number:
            final_notes = f"{final_notes}\nLote afectado: {lot_number}"
        new_severity_status = 'EDITADO'
    else:
        return {'success': False, 'message': 'Acción no reconocida.'}

    if required_adjustment < Decimal('0') and current_stock < abs(required_adjustment):
        deficit = abs(required_adjustment) - current_stock
        return {
            'success': False, 
            'message': (
                f"El ajuste excede el stock disponible de {product_name}. "
                f"Stock actual: {current_stock:.2f} unidades; este ajuste intenta descontar "
                f"{abs(required_adjustment):.2f} unidades. Faltan {deficit:.2f} unidades para poder procesarlo."
            )
        }

    new_qty = current_stock + required_adjustment
    severity = "NORMAL"

    try:
        AuditInventoryRepository.register_audit_adjustment(
            user_id=current_user.id,
            location_id=location_id,
            action_type=final_action,
            severity=severity,
            product_id=product_id,
            product_name=product_name,
            prev_qty=float(current_stock),
            new_qty=float(new_qty),
            qty_changed=float(required_adjustment),
            notes=final_notes,
            original_log_id=log_id,
            new_original_severity=new_severity_status,
            lot_number=lot_number
        )
    except Exception as e:
        return {'success': False, 'message': f'Error en base de datos al registrar el movimiento: {str(e)}'}

    return {'success': True, 'message': 'Acción procesada con éxito.'}


# ============================================================================
# VISOR INGRESOS / EGRESOS (diseño tipo movement_audit)
# ============================================================================

MOVEMENT_EVENT_ACTIONS = {
    'DESPACHO_EMISION',
    'CANCELACION_PRE_SALIDA',
    'RECEPCION_CONFORME',
    'RECEPCION_NOVEDAD',
    'RESOLUCION_DISPUTA',
}

SEV_MAP = {
    'NORMAL': ('NORMAL', 'bg-success', 'bi-check-circle-fill'),
    'ALERTA': ('ALERTA', 'ph-badge-warning', 'bi-exclamation-circle-fill'),
    'CRITICO': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'CRITICAL': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'EDITADO': ('EDITADO', 'bg-warning text-dark', 'bi-pencil-fill'),
    'ANULADO': ('ANULADO', 'bg-danger', 'bi-x-circle-fill'),
    'REABASTECIDO': ('REABASTECIDO', 'bg-info text-white', 'bi-arrow-up-circle-fill'),
}

INCOME_KEYWORDS = ('INGRESO', 'COMPRA', 'RECEPCION', 'REABASTEC', 'ACTIVACION', 'DEVOLUCION', 'ACREDITACION')


def _changed_dict(log):
    c = log.changed_data or {}
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except json.JSONDecodeError:
            c = {}
    return c if isinstance(c, dict) else {}


def _sev_badge(sev):
    sev = (sev or 'NORMAL').upper()
    return SEV_MAP.get(sev, ('NORMAL', 'bg-success', 'bi-check-circle-fill'))


def _fmt_amount(val):
    if val in (None, ''):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _entry_seed(row, sede, product, c, is_admin, read_only_role, now):
    sev = (row.severity or 'NORMAL').upper()
    username = getattr(row, 'user_name', None) or 'Sistema'
    ts = row.timestamp
    ts_aware = None
    if ts is not None:
        ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    entry = {
        'id': row.id,
        'action': row.action or '',
        'sev': sev,
        'sev_label': _sev_badge(sev)[0],
        'sev_class': _sev_badge(sev)[1],
        'sev_icon': _sev_badge(sev)[2],
        'user_name': username,
        'initial': username[0].upper() if username else 'S',
        'ts': ts,
        'sede': sede,
        'movement_id': c.get('movement_id'),
        'notes': c.get('notes', '') if isinstance(c.get('notes'), str) else '',
        'event_type': 'inventory',
        'can_manage': False,
        'manage_mode': None,
        'timed_out_note': '',
        'is_retorno': False,
        'purchase_id': None,
        'can_view_purchase': False,
    }
    return entry, ts_aware, sev


def _apply_manage(entry, ts_aware, sev, act, is_admin, read_only_role, now):
    """Calcula si un log de inventario operativo admite Editar/Anular/Activar."""
    if entry.get('event_type') != 'inventory':
        return
    if read_only_role:
        return
    if 'MERMA' in act or 'COMPRA' in act or 'INGRESO' in act or 'AJUSTE' in act or 'REVERSION' in act or 'ACTIVACION' in act:
        return
    if sev in ('ANULADO',):
        entry['can_manage'] = True
        entry['manage_mode'] = 'ACTIVAR'
        return
    if sev in ('EDITADO',):
        return

    hours = ((now - ts_aware).total_seconds() / 3600.0) if ts_aware else 0
    if not is_admin and hours > 24:
        entry['timed_out_note'] = 'Tiempo expirado (24h). Solicite corrección al Administrador.'
        return
    if is_admin and hours > 720:
        entry['timed_out_note'] = 'Plazo máximo administrativo expirado (30 días).'
        return

    entry['can_manage'] = True
    entry['manage_mode'] = 'EDITAR_ANULAR'


def _push_inventory_rows(rows, log, c, sev, ts_aware, sede, entry, is_admin, read_only_role, now, annulled_target_ids):
    """Crea las filas de un log operativo de stock (quantity_changed)."""
    qty_changed = _fmt_amount(c.get('quantity_changed', 0)) or 0.0
    prev_qty = _fmt_amount(c.get('previous_quantity'))
    new_qty = _fmt_amount(c.get('new_quantity'))

    if qty_changed != 0:
        if qty_changed < 0:
            if prev_qty in (0, 0.0, None):
                if new_qty is not None and new_qty > 0:
                    prev_qty = new_qty - qty_changed
                else:
                    prev_qty = abs(qty_changed)
                    new_qty = 0.0
            elif new_qty is None:
                new_qty = prev_qty + qty_changed
        else:
            if prev_qty in (0, 0.0, None) and new_qty in (0, 0.0, None):
                prev_qty = 0.0
                new_qty = qty_changed
            elif new_qty is None and prev_qty is not None:
                new_qty = prev_qty + qty_changed
            elif prev_qty is None and new_qty is not None:
                prev_qty = new_qty - qty_changed

    if prev_qty is None:
        prev_qty = 0.0
    if new_qty is None:
        new_qty = 0.0
    prev_qty = max(0.0, prev_qty)
    new_qty = max(0.0, new_qty)

    act = (log.action or '').upper()
    is_adjustment = any(kw in act for kw in ['REVERSION', 'AJUSTE', 'ACTIVACION'])

    row_data = dict(entry)
    row_data.update({
        'event_type': 'inventory',
        'product': c.get('product_name') or c.get('producto') or c.get('nombre') or 'N/A',
        'sku': c.get('sku', 'N/A'),
        'lot': c.get('lot_number', 'N/A'),
        'qty': qty_changed,
        'prev_qty': prev_qty,
        'new_qty': new_qty,
        'is_annulled': log.id in annulled_target_ids,
        'is_adjustment': is_adjustment,
    })
    _apply_manage(row_data, ts_aware, sev, act, is_admin, read_only_role, now)
    rows.append(row_data)


def _push_despacho_rows(rows, log, c, entry, origin_name, destination_name, mov_status):
    items = c.get('items') or []
    if not items:
        return
    total = sum(float(i.get('dispatched_qty', 0)) for i in items)
    for it in items:
        row = dict(entry)
        row.update({
            'event_type': 'despacho',
            'product': it.get('product_name') or 'N/A',
            'sku': it.get('sku') or 'N/A',
            'lot': it.get('lot_number') or 'N/A',
            'expiration': it.get('expiration_date') or 'N/A',
            'qty': -float(it.get('dispatched_qty', 0)),
            'dispatched_qty': float(it.get('dispatched_qty', 0)),
            'origin': origin_name,
            'destination': destination_name,
            'movement_status': mov_status,
        })
        rows.append(row)


def _push_cancelacion_rows(rows, log, c, entry, origin_name, destination_name, mov_status):
    delta = _fmt_amount((c.get('stock_impact') or {}).get('origin_current_delta')) or 0.0
    row = dict(entry)
    row.update({
        'event_type': 'cancelacion',
        'product': f"Mercancía devuelta · Baja de traslado",
        'sku': 'N/A',
        'lot': 'N/A',
        'qty': abs(delta),
        'reason': c.get('reason', ''),
        'origin': origin_name,
        'destination': destination_name,
        'movement_status': mov_status,
    })
    rows.append(row)


def _push_recepcion_rows(rows, log, c, entry, origin_name, destination_name, mov_status):
    items = c.get('items') or []
    notes = entry['notes']
    if not items:
        return
    for it in items:
        missing = float(it.get('missing_qty', 0))
        novelty = it.get('specific_novelty', 'CONFORME')
        row = dict(entry)
        row.update({
            'event_type': 'recepcion',
            'product': it.get('product_name') or 'N/A',
            'sku': it.get('sku') or 'N/A',
            'lot': it.get('lot_number') or 'N/A',
            'expiration': it.get('expiration_date') or 'N/A',
            'qty': float(it.get('received_qty', it.get('dispatched_qty', 0))),
            'dispatched_qty': float(it.get('dispatched_qty', 0)),
            'received_qty': float(it.get('received_qty', it.get('dispatched_qty', 0))),
            'missing_qty': missing,
            'novelty': novelty,
            'notes': notes,
            'origin': origin_name,
            'destination': destination_name,
            'movement_status': mov_status,
            'has_novedad': missing > 0.001 or (novelty or '').upper() != 'CONFORME',
        })
        rows.append(row)


def _push_resolucion_rows(rows, log, c, entry, origin_name, destination_name, mov_status):
    summary = c.get('resolution_summary') or {}
    items = c.get('items') or []
    notes = c.get('general_notes', '') or ''
    credited = _fmt_amount(summary.get('credited_total')) or 0.0
    returned = _fmt_amount(summary.get('returned_total')) or 0.0
    lost = _fmt_amount(summary.get('lost_total')) or 0.0

    if credited > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Acreditación por disputa · Traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': credited,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
        })
        rows.append(row)

    if returned > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Devolución a origen por disputa · Traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': returned,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
        })
        rows.append(row)

    if lost > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Mercancía extraviada · Disputa de traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': -lost,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
        })
        rows.append(row)


def _to_naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _resolve_purchase_id(log, c, ts):
    """Vincula un log INGRESO_COMPRA con su compra usando el historial CREATE."""
    pid = c.get('purchase_id')
    if pid:
        try:
            return int(pid)
        except (TypeError, ValueError):
            return None
    if not ts:
        return None
    for pa in (
        PurchaseAuditLog.query
        .filter(PurchaseAuditLog.action_type == 'CREATE', PurchaseAuditLog.user_id == log.user_id)
        .order_by(PurchaseAuditLog.timestamp.desc())
        .all()
    ):
        if pa.timestamp and abs((_to_naive(pa.timestamp) - _to_naive(ts)).total_seconds()) <= 90:
            return pa.purchase_id
    return None


def get_inventory_audit_entries(filters, user, is_admin):
    """
    Devuelve la lista de eventos de inventario (ingresos y egresos) con los
    traslados repartidos por sede:
      - DESPACHO_EMISION    -> egreso en la sede origen (por ítem/lote)
      - CANCELACION_PRE_SALIDA -> ingreso en la sede origen (mercancía devuelta)
      - RECEPCION_*         -> ingreso en la sede destino (por ítem/lote)
      - RESOLUCION_DISPUTA  -> acreditación/devolución (ingreso) y extravío (egreso)
    """
    allowed_locations = None
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return []

    location_id_filter = filters.get('location_id') or None
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    if not is_admin and location_id_filter and location_id_filter not in allowed_locations:
        location_id_filter = None

    severity_filter = (filters.get('severity') or '').upper() or None

    raw_logs = AuditInventoryRepository.get_audit_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        severity_filter=severity_filter,
        start_date=filters.get('start_date') or None,
        end_date=filters.get('end_date') or None,
    )

    # --- Detección de anulados/reactivados (mismo criterio que el JS previo) ---
    annulled_target_ids = set()
    for raw in sorted(raw_logs, key=lambda x: x.id):
        c = _changed_dict(raw)
        notes = c.get('notes', '')
        if isinstance(notes, str):
            m = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
            if m:
                target_id = int(m.group(1))
                if 'REVERSION' in (raw.action or '').upper():
                    annulled_target_ids.add(target_id)
                elif 'ACTIVACION' in (raw.action or '').upper():
                    annulled_target_ids.discard(target_id)

    # --- Mapa de traslados para resoluciones (location_id NULL) ---
    movement_ids = set()
    for raw in raw_logs:
        c = _changed_dict(raw)
        mid = c.get('movement_id')
        if mid is not None:
            try:
                movement_ids.add(int(mid))
            except (TypeError, ValueError):
                pass

    movement_map = {}
    if movement_ids:
        for mov in Movement.query.filter(Movement.id.in_(movement_ids)).all():
            movement_map[mov.id] = mov

    # --- Mapa de productos de mermas (aprobadas y rechazadas) ---
    # El log de MERMA solo guarda waste_id; el detalle (productos/lotes) vive en waste_details.
    merma_waste_ids = set()
    for raw in raw_logs:
        c = _changed_dict(raw)
        if (raw.action or '').upper() == 'MERMA':
            wid = c.get('waste_id')
            if wid is not None:
                try:
                    merma_waste_ids.add(int(wid))
                except (TypeError, ValueError):
                    pass

    merma_details = {}
    product_ids_all = set()
    if merma_waste_ids:
        for wd in WasteDetail.query.filter(WasteDetail.waste_id.in_(merma_waste_ids)).all():
            merma_details.setdefault(wd.waste_id, []).append({
                'product_id': wd.product_id,
                'qty': float(wd.quantity or 0),
                'lot': wd.lot_number or 'N/A',
            })
            product_ids_all.add(wd.product_id)

    product_map = {}
    if product_ids_all:
        for pr in Product.query.filter(Product.id.in_(product_ids_all)).all():
            product_map[pr.id] = pr.name

    location_cache = {}

    def loc_name(loc_id):
        if not loc_id:
            return '—'
        if loc_id not in location_cache:
            loc = Location.query.get(loc_id)
            location_cache[loc_id] = loc.name if loc else f"Sede #{loc_id}"
        return location_cache[loc_id]

    role_id = getattr(user, 'role_id', None)
    read_only_role = role_id in (4, 6)
    can_view_purchase = (
        is_admin
        or bool(getattr(user, 'is_management', False))
        or bool(getattr(user, 'is_manager', False))
        or bool(getattr(user, 'is_finance', False))
    )
    now = datetime.now(timezone.utc)

    rows = []
    for log in raw_logs:
        c = _changed_dict(log)
        act = (log.action or '').upper()
        aff = (getattr(log, 'affected_table', '') or '').lower()
        sev = (log.severity or 'NORMAL').upper()
        sede = getattr(log, 'location_name', None) or c.get('location_name') or 'Almacén Principal'

        is_movement = (
            aff == 'movements'
            and act in MOVEMENT_EVENT_ACTIONS
            and c.get('movement_id') is not None
        )

        entry, ts_aware, sev_upper = _entry_seed(log, sede, None, c, is_admin, read_only_role, now)

        if is_movement:
            mid = int(c['movement_id'])
            mov_obj = movement_map.get(mid)
            origem = mov_obj.origin_location_id if mov_obj else c.get('origin_location_id')
            dest = (mov_obj.destination_location_id if mov_obj else c.get('destination_location_id'))
            if mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA' and not origem:
                origem = mov_obj.destination_location_id
            origin_name = loc_name(origem)
            destination_name = loc_name(dest)
            mov_status = mov_obj.status if mov_obj else None

            entry['movement_id'] = mid
            entry['is_retorno'] = bool(mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA')

            if act == 'DESPACHO_EMISION':
                _push_despacho_rows(rows, log, c, entry, origin_name, destination_name, mov_status)
            elif act == 'CANCELACION_PRE_SALIDA':
                _push_cancelacion_rows(rows, log, c, entry, origin_name, destination_name, mov_status)
            elif act in ('RECEPCION_CONFORME', 'RECEPCION_NOVEDAD'):
                _push_recepcion_rows(rows, log, c, entry, origin_name, destination_name, mov_status)
            elif act == 'RESOLUCION_DISPUTA':
                _push_resolucion_rows(rows, log, c, entry, origin_name, destination_name, mov_status)
            continue

        # --- Mermas: mostrar TODAS (aprobadas, rechazadas, canceladas, editadas) con su detalle y observación ---
        if act == 'MERMA':
            event = (c.get('event') or '').upper()
            wid = c.get('waste_id')
            try:
                wid = int(wid) if wid is not None else None
            except (TypeError, ValueError):
                wid = None

            detalles = merma_details.get(wid) or []
            stock_map = {}
            admin_name = 'Administración'
            motivo = ''
            if event == 'MERMA_APROBADA':
                admin_name = c.get('approved_by') or 'Administración'
                # stock real por producto desde descuentos_stock
                for it in c.get('descuentos_stock') or []:
                    pid = it.get('product_id')
                    try:
                        pid = int(pid) if pid is not None else None
                    except (TypeError, ValueError):
                        pid = None
                    if pid is None:
                        continue
                    try:
                        stock_map[pid] = (
                            float(it.get('stock_antes') or 0),
                            float(it.get('stock_despues') or 0),
                            float(it.get('quantity') or 0),
                        )
                    except (TypeError, ValueError):
                        stock_map[pid] = (0.0, 0.0, 0.0)
            elif event == 'MERMA_CANCELADA' or event == 'MERMA_EDITADA':
                admin_name = c.get('cancelled_by') or c.get('edited_by') or 'el autor'
                motivo = c.get('motivo_cancelacion') or c.get('motivo_edicion') or ''
            else:
                admin_name = c.get('rejected_by') or 'Administración'
                motivo = c.get('motivo_rechazo') or ''

            # Si no hay detalle en waste_details (dato suplementario), usamos descuentos_stock
            if not detalles:
                detalles = [
                    {'product_id': pid, 'qty': stock_map.get(pid, (0, 0, 0))[2], 'lot': 'N/A'}
                    for pid in stock_map
                ]

            # Cancelación de una merma PENDIENTE: nunca descontó stock.
            # Se muestra UNA fila por log (con el motivo), sin líneas.
            if event == 'MERMA_CANCELADA':
                nombres = [product_map.get(d.get('product_id')) for d in detalles]
                nombres = [n for n in nombres if n]
                producto = ' · '.join(list(dict.fromkeys(nombres))[:2]) or 'Merma'

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': producto,
                    'sku': 'N/A',
                    'lot': 'N/A',
                    'qty': 0.0,
                    'prev_qty': 0.0,
                    'new_qty': 0.0,
                    'is_merma': True,
                    'is_merma_rejected': False,
                    'is_merma_cancelled': True,
                    'is_merma_edited': False,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                    'notes': (
                        f"Cancelación de la merma{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    ),
                })
                rows.append(merma_row)
                continue

            # Edición de una merma PENDIENTE: tampoco descontó stock.
            # Una fila por log; si el evento guardó cantidades, se muestran antes → después.
            if event == 'MERMA_EDITADA':
                nombres = [product_map.get(d.get('product_id')) for d in detalles]
                nombres = [n for n in nombres if n]
                producto = ' · '.join(list(dict.fromkeys(nombres))[:2]) or 'Merma'

                cantidad_txt = ''
                antes = c.get('cantidad_antes')
                despues = c.get('cantidad_despues')
                if antes is not None and despues is not None:
                    try:
                        cantidad_txt = f" Cantidad: {float(antes):.2f} → {float(despues):.2f}."
                    except (TypeError, ValueError):
                        cantidad_txt = ''

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': producto,
                    'sku': 'N/A',
                    'lot': 'N/A',
                    'qty': 0.0,
                    'prev_qty': 0.0,
                    'new_qty': 0.0,
                    'is_merma': True,
                    'is_merma_rejected': False,
                    'is_merma_cancelled': False,
                    'is_merma_edited': True,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                    'notes': (
                        f"Edición de la merma{(' #' + str(wid)) if wid else ''} por {admin_name}."
                        f"{cantidad_txt} Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    ),
                })
                rows.append(merma_row)
                continue

            for d in detalles:
                pid = d.get('product_id')
                try:
                    pid = int(pid) if pid is not None else None
                except (TypeError, ValueError):
                    pid = None
                qty_nominal = float(d.get('qty') or 0)
                stock_antes, stock_despues, qty_disc = stock_map.get(pid, (0.0, 0.0, qty_nominal))
                qty = qty_disc if qty_disc else qty_nominal

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': product_map.get(pid, f'Insumo #{pid}' if pid else 'N/A'),
                    'sku': 'N/A',
                    'lot': d.get('lot') or 'N/A',
                    'qty': -qty,
                    'is_merma': True,
                    'is_merma_rejected': event != 'MERMA_APROBADA',
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                })
                if event == 'MERMA_APROBADA':
                    merma_row['prev_qty'] = stock_antes
                    merma_row['new_qty'] = stock_despues
                    merma_row['notes'] = (
                        f"Merma aprobada{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Stock: {stock_antes:.2f} → {stock_despues:.2f}."
                    )
                else:
                    # Rechazada: sin descuento de stock (prev == new == 0)
                    merma_row['prev_qty'] = 0.0
                    merma_row['new_qty'] = 0.0
                    merma_row['notes'] = (
                        f"Merma RECHAZADA{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    )
                rows.append(merma_row)
            continue

        # --- Logs operativos de stock ---
        if 'COMPRA' in act or 'INGRESO' in act:
            entry['purchase_id'] = _resolve_purchase_id(log, c, log.timestamp)
            entry['can_view_purchase'] = can_view_purchase

        _push_inventory_rows(
            rows, log, c, sev, ts_aware, sede, entry,
            is_admin, read_only_role, now, annulled_target_ids
        )

    return rows


def get_filters_date_range(user, is_admin, location_id_filter):
    """Rango (min, max) de fechas con registros para acotar el calendario."""
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    allowed_locations = None
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return None, None

    return AuditInventoryRepository.get_audit_logs_date_range(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
    )