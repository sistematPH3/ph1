import json
import re
from datetime import datetime
from decimal import Decimal

from app.analytics.repositories.analysis_reports_repository import _ultimo_costo_compra
from app.inventory.repositories.kitchen_expense_audit_repository import (
    BASE_CONSUMPTION_ACTIONS,
    KitchenExpenseAuditRepository,
)
from app.time_utils import TZ_VENEZUELA

_SEV_MAP = {
    'NORMAL': ('NORMAL', 'bg-success', 'bi-check-circle-fill'),
    'ALERTA': ('ALERTA', 'ph-badge-warning', 'bi-exclamation-circle-fill'),
    'CRITICO': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'CRITICAL': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'EDITADO': ('EDITADO', 'bg-warning text-dark', 'bi-pencil-fill'),
    'ANULADO': ('ANULADO', 'bg-danger', 'bi-x-circle-fill'),
}

# =========================================================================
# AYUDAS INTERNAS
# =========================================================================

def _changed_dict(log):
    c = log.changed_data or {}
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except (json.JSONDecodeError, TypeError):
            c = {}
    return c if isinstance(c, dict) else {}


def _qty_str(value):
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    if d == d.to_integral_value():
        return str(int(d))
    return ("%f" % float(d)).rstrip("0").rstrip(".")


def _sev_badge(sev):
    sev = (sev or 'NORMAL').upper()
    return _SEV_MAP.get(sev, _SEV_MAP['NORMAL'])


def _resolve_qty(c):
    qty_changed = c.get('quantity_changed', 0)
    try:
        qty_changed = float(qty_changed)
    except (TypeError, ValueError):
        qty_changed = 0.0

    prev_qty = c.get('previous_quantity')
    new_qty = c.get('new_quantity')
    try:
        prev_qty = float(prev_qty) if prev_qty not in (None, '') else None
    except (TypeError, ValueError):
        prev_qty = None
    try:
        new_qty = float(new_qty) if new_qty not in (None, '') else None
    except (TypeError, ValueError):
        new_qty = None

    if qty_changed < 0:
        if prev_qty in (0, 0.0, None):
            prev_qty = (new_qty - qty_changed) if (new_qty is not None and new_qty > 0) else abs(qty_changed)
            if new_qty is None or not (new_qty is not None and new_qty > 0):
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
            prev_qty = float(new_qty) - qty_changed

    if prev_qty is None:
        prev_qty = 0.0
    if new_qty is None:
        new_qty = 0.0
    prev_qty = max(0.0, prev_qty)
    new_qty = max(0.0, new_qty)
    return prev_qty, new_qty, qty_changed


def _valorizar(c, qty_changed):
    """Monto del gasto: cantidad consumida (o repuesta) × último costo de compra.
    Devuelve (Decimal monto, moneda) o (None, None) si no hay con qué valorizar."""
    try:
        product_id = int(c.get('product_id')) if c.get('product_id') is not None else None
    except (TypeError, ValueError):
        product_id = None
    lot = c.get('lot_number')
    if not lot or str(lot).strip() in ('', 'N/A'):
        lot = None
    try:
        cantidad = Decimal(str(abs(qty_changed)))
    except (TypeError, ValueError):
        cantidad = Decimal('0.00')
    if product_id is None or not cantidad:
        return None, None

    precio, moneda = _ultimo_costo_compra(product_id, lot)
    if precio is None or precio == 0:
        return None, None
    return (cantidad * precio).quantize(Decimal('0.01')), moneda


def _annulled_target_ids(raw_logs):
    """Detecta, sobre el conjunto completo de logs relacionados, qué consumos
    originales fueron anulados/reactivados mediante los movimientos
    compensatorios REVERSION_*/ACTIVACION_* (mismo criterio que AuditInventory)."""
    targets = set()
    for log in sorted(raw_logs, key=lambda x: x.id):
        c = _changed_dict(log)
        notes = c.get('notes', '')
        if isinstance(notes, str):
            m = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
            if m:
                target_id = int(m.group(1))
                act = (log.action or '').upper()
                if 'REVERSION' in act:
                    targets.add(target_id)
                elif 'ACTIVACION' in act or 'REACTIVACION' in act:
                    targets.discard(target_id)
    return targets


# =========================================================================
# VISOR DE LA AUDITORÍA
# =========================================================================

def get_kitchen_expense_locations(user, is_admin):
    locations = KitchenExpenseAuditRepository.get_all_locations()
    if is_admin:
        return locations
    allowed = KitchenExpenseAuditRepository.get_user_allowed_locations(user.id)
    return [loc for loc in locations if loc.id in allowed]


def get_kitchen_expense_entries(filters, user, is_admin):
    """Lista de eventos lista para la vista. 'base' trae los consumos originales;
    'ajustes' trae los movimientos compensatorios (ediciones/anulaciones/activaciones)."""
    allowed_locations = None
    if not is_admin:
        allowed_locations = KitchenExpenseAuditRepository.get_user_allowed_locations(user.id)
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
    action_mode = 'adjustments' if filters.get('tab') == 'ajustes' else 'base'

    raw_logs = KitchenExpenseAuditRepository.get_consumption_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        severity_filter=severity_filter,
        start_date=filters.get('start_date') or None,
        end_date=filters.get('end_date') or None,
        action_mode=action_mode,
    )

    # Para marcar consumos anulados/reactivados se escanea el conjunto completo
    # (base + compensatorios) con el mismo alcance de sedes, sin límite de pestaña.
    annulled_ids = set()
    if action_mode == 'base':
        scan_logs = KitchenExpenseAuditRepository.get_consumption_logs(
            allowed_locations=allowed_locations,
            location_id_filter=location_id_filter,
            severity_filter=severity_filter,
            start_date=filters.get('start_date') or None,
            end_date=filters.get('end_date') or None,
            action_mode='all',
        )
        annulled_ids = _annulled_target_ids(scan_logs)

    role_id = getattr(user, 'role_id', None)
    read_only_role = role_id in (4, 6)
    now = datetime.now(TZ_VENEZUELA)

    rows = []
    for log in raw_logs:
        c = _changed_dict(log)
        act = (log.action or '').upper()
        sev = (log.severity or 'NORMAL').upper()
        prev_qty, new_qty, qty_changed = _resolve_qty(c)

        username = log.user_name or f'Usuario ID: {log.user_id}'
        sede = log.location_name or c.get('location_name') or 'Sede desconocida'
        notes = c.get('notes', '') if isinstance(c.get('notes'), str) else ''

        ts = log.timestamp
        ts_aware = None
        if ts is not None:
            ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=TZ_VENEZUELA)

        sev_label, sev_class, sev_icon = _sev_badge(sev)

        def _num(value):
            try:
                return float(value) if value not in (None, '') else None
            except (TypeError, ValueError):
                return None

        gasto_orig = _num(c.get('original_quantity'))
        gasto_new = _num(c.get('edited_quantity'))

        # Monto valorizado al ÚLTIMO costo de compra. Si el gasto fue corregido
        # (editado/anulado/reactivado) se valoriza la cantidad VIGENTE
        # ('edited_quantity'), conservando el monto original para mostrarlo tachado.
        es_correccion = act in BASE_CONSUMPTION_ACTIONS and gasto_new is not None
        qty_vigente = -gasto_new if es_correccion else qty_changed
        amount, currency = _valorizar(c, qty_vigente)
        amount_orig = None
        if es_correccion and gasto_new != gasto_orig:
            amount_orig, _mon = _valorizar(c, qty_changed)
            if currency is None:
                currency = _mon
        try:
            product_id = int(c.get('product_id')) if c.get('product_id') is not None else None
        except (TypeError, ValueError):
            product_id = None
        target_log_id = c.get('target_log_id')
        if target_log_id in (None, ''):
            target_log_id = c.get('adjustment_log_id')
        if target_log_id in (None, ''):
            m = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
            target_log_id = int(m.group(1)) if m else None

        is_adjustment_action = any(kw in act for kw in ('AJUSTE', 'REVERSION', 'ACTIVACION'))
        # El gasto original conserva sus valores; la corrección se refleja como
        # "viejo -> nuevo" en la pestaña de Ajustes (gasto_orig / gasto_new).
        is_corrected = (
            gasto_orig is not None and gasto_new is not None and gasto_new != gasto_orig
        )

        can_manage, manage_mode, manage_note = _manage_state(
            act, sev, ts_aware, now, is_admin, read_only_role, log.location_id
        )

        rows.append({
            'id': log.id,
            'action': log.action or '',
            'sev': sev,
            'sev_label': sev_label,
            'sev_class': sev_class,
            'sev_icon': sev_icon,
            'user_name': username,
            'initial': username[0].upper() if username else 'S',
            'ts': ts_aware,
            'sede': sede,
            'product': c.get('product_name') or 'Insumo no especificado',
            'lot': c.get('lot_number') or 'N/A',
            'loc_id': log.location_id,
            'product_id': product_id,
            'has_physical': 'previous_physical_quantity' not in c,
            'qty': qty_changed,
            'prev_qty': prev_qty,
            'new_qty': new_qty,
            'gasto_orig': gasto_orig,
            'gasto_new': gasto_new,
            'target_log_id': target_log_id,
            'is_corrected': is_corrected,
            'notes': notes,
            'amount': amount,
            'amount_orig': amount_orig,
            'currency': currency,
            'is_adjustment': is_adjustment_action,
            'is_annulled': log.id in annulled_ids,
            'can_manage': can_manage,
            'manage_mode': manage_mode,
            'manage_note': manage_note,
        })

    # Los stock almacenados corresponden al físico; para mostrar el "disponible"
    # real se descuenta el congelado actual (tránsito + reservado) en los registros
    # que guardaron físico (los ajustes nuevos ya guardan disponible).
    pairs = [(r['loc_id'], r['product_id']) for r in rows if r['loc_id'] and r['product_id']]
    frozen_map = KitchenExpenseAuditRepository.get_inventory_frozen_map(
        [p[0] for p in pairs], [p[1] for p in pairs]
    ) if pairs else {}
    for r in rows:
        if r.get('has_physical') and (r['loc_id'], r['product_id']) in frozen_map:
            f = frozen_map[(r['loc_id'], r['product_id'])]
            if f:
                r['prev_qty'] = max(0.0, r['prev_qty'] - f)
                r['new_qty'] = max(0.0, r['new_qty'] - f)

    # 'current_qty' = stock disponible real HOY (físico - tránsito - reservado),
    # para que el gasto corregido muestre el disponible vigente y no el histórico.
    available_map = KitchenExpenseAuditRepository.get_current_available_map(
        [p[0] for p in pairs], [p[1] for p in pairs]
    ) if pairs else {}
    for r in rows:
        key = (r['loc_id'], r['product_id'])
        r['current_qty'] = float(available_map[key] if key in available_map else r['new_qty'])

    rows.sort(key=lambda r: r['ts'] or datetime.min.replace(tzinfo=TZ_VENEZUELA), reverse=True)
    return rows


def _manage_state(act, sev, ts_aware, now, is_admin, read_only_role, location_id):
    """Reglas de edición con límites (portadas de AuditInventory):
    - Los registros ya editados no se vuelven a tocar; los anulados solo se activan.
    - Ventanas de tiempo: 24 h sin ser admin, 30 días para administradores.
    - El Almacén General (sede 1) no admite modificaciones de gastos."""
    if read_only_role:
        return False, None, ''
    if act not in BASE_CONSUMPTION_ACTIONS:
        return False, None, ''
    if location_id in (1, None):
        return False, None, 'Los gastos en el Almacén General no admiten modificaciones.'
    if sev == 'ANULADO':
        return True, 'ACTIVAR', ''
    if sev == 'EDITADO':
        return False, None, 'Este registro ya fue editado y quedó como registro contable inmutable.'

    hours = ((now - ts_aware).total_seconds() / 3600.0) if ts_aware else 0
    if not is_admin and hours > 24:
        return False, None, 'Tiempo expirado (24h). Solicite la corrección al Administrador.'
    if is_admin and hours > 720:
        return False, None, 'Plazo máximo administrativo expirado (30 días).'

    return True, 'EDITAR_ANULAR', ''


def get_kitchen_expense_counts(filters, user, is_admin):
    """Conteo de gastos originales y movimientos compensatorios para las pestañas."""
    allowed_locations = None
    if not is_admin:
        allowed_locations = KitchenExpenseAuditRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return {'gastos': 0, 'ajustes': 0}

    location_id_filter = filters.get('location_id') or None
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    severity_filter = (filters.get('severity') or '').upper() or None

    counts = {'gastos': 0, 'ajustes': 0}
    for mode, key in (('base', 'gastos'), ('adjustments', 'ajustes')):
        rows = KitchenExpenseAuditRepository.get_consumption_logs(
            allowed_locations=allowed_locations,
            location_id_filter=location_id_filter,
            severity_filter=severity_filter,
            start_date=filters.get('start_date') or None,
            end_date=filters.get('end_date') or None,
            action_mode=mode,
        )
        counts[key] = len(rows)
    return counts


def get_consumption_date_range(filters, user, is_admin):
    """Rango (min, max) de fechas con consumos, respetando el alcance de sedes."""
    allowed_locations = None
    if not is_admin:
        allowed_locations = KitchenExpenseAuditRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return None, None

    location_id_filter = filters.get('location_id') or None
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    return KitchenExpenseAuditRepository.get_consumption_logs_date_range(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
    )


# =========================================================================
# EDICIÓN CON LÍMITES
# =========================================================================

def process_kitchen_expense_action(log_id, current_user, action_type,
                                   new_quantity_requested=None,
                                   justification_notes='', lot_number=None):
    """Editar / Anular / Activar un gasto de cocina registrado, con las mismas
    limitaciones que AuditInventory: solo consumos originales, fuera del Almacén
    General, dentro de la ventana de tiempo, con motivo obligatorio y sin exceder
    el stock disponible."""
    log = KitchenExpenseAuditRepository.get_audit_log_by_id(log_id)
    if not log:
        return {'success': False, 'message': 'El registro de auditoría solicitado no existe.'}

    action_name = log.action or ''
    action_upper = action_name.upper()

    if action_upper not in BASE_CONSUMPTION_ACTIONS:
        return {
            'success': False,
            'message': 'Solo los gastos de cocina originales admiten esta acción. Los registros compensatorios son inmutables.',
        }

    if log.location_id == 1:
        return {
            'success': False,
            'message': 'Operación denegada. Los gastos registrados en el Almacén General no admiten modificaciones.',
        }

    role_id = getattr(current_user, 'role_id', None)
    is_admin = (role_id == 1)
    if role_id == 6:
        return {
            'success': False,
            'message': 'Operación denegada. El perfil de finanzas posee atributos de solo lectura.',
        }

    log_timestamp = log.timestamp
    if log_timestamp is not None and log_timestamp.tzinfo is None:
        log_timestamp = log_timestamp.replace(tzinfo=TZ_VENEZUELA)

    now = datetime.now(TZ_VENEZUELA)
    diff_hours = (now - log_timestamp).total_seconds() / 3600
    if not is_admin:
        if diff_hours > 24:
            return {
                'success': False,
                'message': 'El tiempo límite de 24 horas ha expirado. Solicite la acción al Administrador.',
            }
    else:
        if diff_hours > 30 * 24:
            return {
                'success': False,
                'message': 'El límite máximo de 30 días permitido para administradores ha expirado.',
            }

    c = _changed_dict(log)

    product_id = c.get('product_id')
    try:
        product_id = int(product_id) if product_id is not None else None
    except (TypeError, ValueError):
        product_id = None
    product_name = c.get('product_name') or 'Insumo no especificado'
    if product_id is None:
        return {
            'success': False,
            'message': 'El registro carece del identificador del insumo necesario para procesar la acción.',
        }

    original_qty_changed = Decimal(str(c.get('quantity_changed') or 0))
    if original_qty_changed == 0:
        p = c.get('previous_quantity')
        n = c.get('new_quantity')
        if p is not None and n is not None:
            try:
                original_qty_changed = Decimal(str(n)) - Decimal(str(p))
            except (TypeError, ValueError):
                original_qty_changed = Decimal('0')

    _inv_state = KitchenExpenseAuditRepository.get_inventory_state(log.location_id, product_id)
    physical_stock = Decimal('0.00') if _inv_state.get('current_quantity') is None else Decimal(str(_inv_state.get('current_quantity')))
    transit_stock = Decimal('0.00') if _inv_state.get('transit_quantity') is None else Decimal(str(_inv_state.get('transit_quantity')))
    reserved_stock = Decimal('0.00') if _inv_state.get('reserved_quantity') is None else Decimal(str(_inv_state.get('reserved_quantity')))
    current_stock = physical_stock - transit_stock - reserved_stock

    new_severity_status = None

    if action_type == 'ANULAR':
        required_adjustment = -original_qty_changed
        final_action = f'REVERSION_{action_name}'
        final_notes = f'Anulación del log #{log_id}. Motivo: {justification_notes}'
        new_severity_status = 'ANULADO'
        gasto_original = abs(original_qty_changed)
        gasto_editado = Decimal('0')
    elif action_type == 'ACTIVAR':
        required_adjustment = original_qty_changed
        final_action = f'ACTIVACION_{action_name}'
        final_notes = f'Reactivación del log #{log_id}. Motivo: {justification_notes}'
        new_severity_status = 'NORMAL'
        gasto_original = abs(original_qty_changed)
        gasto_editado = abs(original_qty_changed)
    elif action_type == 'EDITAR':
        if new_quantity_requested is None:
            return {
                'success': False,
                'message': 'Debe especificar la cantidad real gastada para procesar la edición.',
            }
        new_requested_dec = Decimal(str(new_quantity_requested))
        abs_original = abs(original_qty_changed)
        abs_new = abs(new_requested_dec)
        required_adjustment = abs_original - abs_new
        final_action = f'AJUSTE_{action_name}'
        final_notes = (
            f'Edición del log #{log_id}: cantidad corregida de {_qty_str(abs_original)} '
            f'a {_qty_str(abs_new)} unidades. Motivo: {justification_notes}'
        )
        if lot_number:
            final_notes = f'{final_notes}\nLote afectado: {lot_number}'
        new_severity_status = 'EDITADO'
        gasto_original = abs_original
        gasto_editado = abs_new
    else:
        return {'success': False, 'message': 'Acción no reconocida.'}

    if required_adjustment < Decimal('0') and current_stock < abs(required_adjustment):
        deficit = abs(required_adjustment) - current_stock
        return {
            'success': False,
            'message': (
                f'El ajuste excede el stock disponible de {product_name}. '
                f'Stock actual: {_qty_str(current_stock)} unidades; este ajuste intenta descontar '
                f'{_qty_str(abs(required_adjustment))} unidades. Faltan {_qty_str(deficit)} unidades para poder procesarlo.'
            ),
        }

    new_qty = current_stock + required_adjustment
    new_physical_qty = physical_stock + required_adjustment

    try:
        KitchenExpenseAuditRepository.register_consumption_adjustment(
            user_id=current_user.id,
            location_id=log.location_id,
            action_type=final_action,
            severity='NORMAL',
            product_id=product_id,
            product_name=product_name,
            prev_qty=float(current_stock),
            new_qty=float(new_qty),
            qty_changed=float(required_adjustment),
            prev_physical_qty=float(physical_stock),
            new_physical_qty=float(new_physical_qty),
            original_quantity=float(gasto_original),
            edited_quantity=float(gasto_editado),
            notes=final_notes,
            original_log_id=log_id,
            new_original_severity=new_severity_status,
            lot_number=lot_number or c.get('lot_number'),
        )
    except Exception as e:
        return {
            'success': False,
            'message': f'Error en base de datos al registrar el movimiento: {str(e)}',
        }

    return {'success': True, 'message': 'Acción procesada con éxito.'}