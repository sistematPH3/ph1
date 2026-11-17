import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.analytics.repositories.analysis_reports_repository import _ultimo_costo_compra
from app.inventory.repositories.kitchen_expense_audit_repository import (
    ADJUSTMENT_ACTION_PREFIXES,
    BASE_CONSUMPTION_ACTIONS,
    CENTRAL_WAREHOUSE_ID,
    KitchenExpenseAuditRepository,
)
from app.time_utils import TZ_VENEZUELA

logger = logging.getLogger(__name__)

# Roles con atributos de solo lectura en la auditoría: no pueden editar,
# anular ni reactivar gastos (solo consultar).
READ_ONLY_ROLE_IDS = (4, 6)

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


def _adjustment_target_id(log):
    """ID del gasto de cocina original al que apunta un movimiento compensatorio.
    Se toma de 'target_log_id' y, en registros heredados, de la referencia
    'log #N' incluida en las notas."""
    c = _changed_dict(log)
    raw = c.get('target_log_id')
    if raw in (None, ''):
        raw = c.get('adjustment_log_id')
    if raw in (None, ''):
        notes = c.get('notes')
        if isinstance(notes, str):
            m = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
            raw = m.group(1) if m else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _base_consumption_ids(allowed_locations, location_id_filter):
    """IDs de los gastos de cocina originales dentro del alcance de sedes."""
    logs = KitchenExpenseAuditRepository.get_consumption_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        action_mode='base',
    )
    return {log.id for log in logs}


def _is_compensation_action(log):
    """True solo para acciones compensatorias reales (AJUSTE_/REVERSION_/
    ACTIVACION_). Un consumo original puro nunca es una compensación."""
    act = (log.action or '').upper()
    return act not in BASE_CONSUMPTION_ACTIONS and act.startswith(ADJUSTMENT_ACTION_PREFIXES)


def _only_linked_adjustments(raw_logs, base_ids):
    """La pestaña de Ajustes es un historial EXCLUSIVO de cambios posteriores:
    solo se listan movimientos compensatorios reales que apuntan a un gasto de
    cocina original existente. Ni un consumo histórico puro ni un compensatorio
    huérfano pueden aparecer aquí."""
    return [
        log for log in raw_logs
        if _is_compensation_action(log) and _adjustment_target_id(log) in base_ids
    ]


def _require_return_lot(lot_number, product_id, location_id):
    """Lote obligatorio y validado para CUALQUIER devolución de stock (edición a
    la baja o anulación). Devuelve (lote_normalizado, mensaje_error)."""
    lot = str(lot_number).strip() if isinstance(lot_number, str) else ''
    if not lot or lot.upper() in ('N/A', 'NONE', 'SIN LOTE'):
        return None, (
            'Debe indicar el lote real de origen del insumo para devolver stock. '
            'Sin lote no se puede preservar la trazabilidad de vencimientos y FIFO.'
        )
    check = KitchenExpenseAuditRepository.validate_return_lot(
        lot, product_id, location_id)
    if not check.get('is_valid'):
        return None, check.get('message') or 'El lote indicado no es válido para esta devolución.'
    return check.get('lot_number', lot), None


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
    # El Almacén Central no tiene gastos de cocina: si se fuerza el filtro, no
    # se devuelve ningún registro (nunca se amplía el alcance silenciosamente).
    if location_id_filter == CENTRAL_WAREHOUSE_ID:
        return []
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
    else:
        raw_logs = _only_linked_adjustments(
            raw_logs,
            _base_consumption_ids(allowed_locations, location_id_filter),
        )

    role_id = getattr(user, 'role_id', None)
    read_only_role = role_id in READ_ONLY_ROLE_IDS
    now = datetime.now(TZ_VENEZUELA)

    rows = []
    for log in raw_logs:
        c = _changed_dict(log)
        act = (log.action or '').upper()
        sev = (log.severity or 'NORMAL').upper()
        prev_qty, new_qty, qty_changed = _resolve_qty(c)

        if log.user_id is None:
            username = 'Usuario no registrado'
        else:
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
            'user_id': log.user_id,
            'user_name': username,
            'initial': username[0].upper() if username else 'S',
            'ts': ts_aware,
            'sede': sede,
            'sede_id': log.location_id,
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

    # 'current_qty' = stock disponible real HOY (físico - reservado; el tránsito
    # ya está descontado de current_quantity al despachar), para que el gasto
    # corregido muestre el disponible vigente y no el histórico.
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
    - Los registros ya editados no se vuelven a tocar; los anulados solo los
      reactiva el Administrador (sin límite de tiempo).
    - Ventanas de tiempo: 24 h sin ser admin, 7 días para administradores.
    - El Almacén Central (sede 1) no admite modificaciones de gastos."""
    if read_only_role:
        return False, None, 'Perfil de solo lectura: no puede modificar gastos de cocina.'
    if act not in BASE_CONSUMPTION_ACTIONS:
        return False, None, ''
    if location_id in (CENTRAL_WAREHOUSE_ID, None):
        return False, None, (
            'Los gastos de cocina solo se registran en sedes operativas; '
            'el Almacén Central no admite modificaciones.'
        )
    if sev == 'ANULADO':
        if is_admin:
            return True, 'ACTIVAR', ''
        return False, None, 'Registro anulado: solo el Administrador puede reactivarlo.'
    if sev == 'EDITADO':
        return False, None, 'Este registro ya fue editado y quedó como registro contable inmutable.'

    hours = ((now - ts_aware).total_seconds() / 3600.0) if ts_aware else 0
    if not is_admin and hours > 24:
        return False, None, 'Tiempo expirado (24h). Solicite la corrección al Administrador.'
    if is_admin and hours > 168:
        return False, None, 'Plazo máximo administrativo expirado (7 días).'

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
    if location_id_filter == CENTRAL_WAREHOUSE_ID:
        return {'gastos': 0, 'ajustes': 0}

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
        if mode == 'adjustments':
            rows = _only_linked_adjustments(
                rows,
                _base_consumption_ids(allowed_locations, location_id_filter),
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
    if location_id_filter == CENTRAL_WAREHOUSE_ID:
        return None, None

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
    # El motivo es obligatorio en el backend (no solo en el formulario): sin
    # justificación no se genera ningún movimiento compensatorio.
    motivo = justification_notes.strip() if isinstance(justification_notes, str) else ''
    if not motivo:
        return {
            'success': False,
            'message': 'Debe proporcionar un motivo obligatorio para realizar esta acción.',
        }

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

    if log.location_id in (CENTRAL_WAREHOUSE_ID, None):
        return {
            'success': False,
            'message': 'Operación denegada. Los gastos de cocina pertenecen a sedes operativas; el Almacén Central no admite modificaciones.',
        }

    role_id = getattr(current_user, 'role_id', None)
    is_admin = (role_id == 1)
    if role_id in READ_ONLY_ROLE_IDS:
        return {
            'success': False,
            'message': 'Operación denegada. Este perfil posee atributos de solo lectura.',
        }

    current_sev = (log.severity or 'NORMAL').upper()
    if action_type == 'ACTIVAR':
        if not is_admin:
            return {
                'success': False,
                'message': 'Operación denegada. Solo el Administrador puede reactivar un gasto anulado.',
            }
        if current_sev != 'ANULADO':
            return {
                'success': False,
                'message': 'Solo se puede reactivar un gasto que se encuentre anulado.',
            }
    elif action_type == 'ANULAR' and current_sev == 'ANULADO':
        return {
            'success': False,
            'message': 'Este gasto ya fue anulado. Una anulación solo puede aplicarse una vez.',
        }
    elif action_type == 'EDITAR' and current_sev in ('EDITADO', 'ANULADO'):
        return {
            'success': False,
            'message': 'Este gasto ya fue editado o anulado y no admite nuevas ediciones.',
        }

    log_timestamp = log.timestamp
    if log_timestamp is not None and log_timestamp.tzinfo is None:
        log_timestamp = log_timestamp.replace(tzinfo=TZ_VENEZUELA)

    now = datetime.now(TZ_VENEZUELA)
    # La reactivación (exclusiva del Administrador) no está sujeta a la ventana
    # de edición: puede ejecutarse aunque el gasto supere la semana.
    if action_type != 'ACTIVAR' and log_timestamp is not None:
        diff_hours = (now - log_timestamp).total_seconds() / 3600
        if not is_admin:
            if diff_hours > 24:
                return {
                    'success': False,
                    'message': 'El tiempo límite de 24 horas ha expirado. Solicite la acción al Administrador.',
                }
        else:
            if diff_hours > 7 * 24:
                return {
                    'success': False,
                    'message': 'El límite máximo de 7 días permitido para administradores ha expirado.',
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

    # Gasto VIGENTE: si el registro ya fue editado, el stock a revertir es la
    # cantidad corregida, no la original. Así la anulación devuelve exactamente
    # lo que la sede descontó por ese gasto.
    base_abs = abs(original_qty_changed)
    edited_raw = c.get('edited_quantity')
    try:
        effective_abs = abs(Decimal(str(edited_raw))) if edited_raw not in (None, '') else base_abs
    except (InvalidOperation, TypeError, ValueError):
        effective_abs = base_abs
    if effective_abs == 0 and base_abs > 0:
        effective_abs = base_abs

    _inv_state = KitchenExpenseAuditRepository.get_inventory_state(log.location_id, product_id)
    physical_stock = Decimal('0.00') if _inv_state.get('current_quantity') is None else Decimal(str(_inv_state.get('current_quantity')))
    reserved_stock = Decimal('0.00') if _inv_state.get('reserved_quantity') is None else Decimal(str(_inv_state.get('reserved_quantity')))
    # El tránsito ya está descontado de current_quantity al despachar.
    current_stock = physical_stock - reserved_stock

    new_severity_status = None

    if action_type == 'ANULAR':
        # Reversión de stock: se devuelve a la sede el gasto vigente completo,
        # de forma atómica junto con el movimiento compensatorio.
        required_adjustment = effective_abs
        final_action = f'REVERSION_{action_name}'
        final_notes = f'Anulación del log #{log_id}. Motivo: {motivo}'
        new_severity_status = 'ANULADO'
        gasto_original = base_abs
        gasto_editado = effective_abs
    elif action_type == 'ACTIVAR':
        required_adjustment = -effective_abs
        final_action = f'ACTIVACION_{action_name}'
        final_notes = f'Reactivación del log #{log_id}. Motivo: {motivo}'
        new_severity_status = 'NORMAL'
        gasto_original = base_abs
        gasto_editado = effective_abs
    elif action_type == 'EDITAR':
        if new_quantity_requested is None:
            return {
                'success': False,
                'message': 'Debe especificar la cantidad real gastada para procesar la edición.',
            }
        new_requested_dec = Decimal(str(new_quantity_requested))
        abs_original = effective_abs
        abs_new = abs(new_requested_dec)
        required_adjustment = abs_original - abs_new
        final_action = f'AJUSTE_{action_name}'
        final_notes = (
            f'Edición del log #{log_id}: cantidad corregida de {_qty_str(abs_original)} '
            f'a {_qty_str(abs_new)} unidades. Motivo: {motivo}'
        )
        new_severity_status = 'EDITADO'
        gasto_original = abs_original
        gasto_editado = abs_new
    else:
        return {'success': False, 'message': 'Acción no reconocida.'}

    # Toda devolución de stock (edición a la baja o anulación) exige un lote real
    # del insumo y de la sede, validado contra compras, traslados y mermas ANTES
    # de tocar el inventario.
    lot_return = None
    if required_adjustment > Decimal('0'):
        lot_return, lot_error = _require_return_lot(
            lot_number, product_id, log.location_id)
        if lot_error:
            return {'success': False, 'message': lot_error}
        final_notes = f'{final_notes}\nLote devuelto: {lot_return}'

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
            lot_number=(lot_return
                        or (str(lot_number).strip() if lot_number else None)
                        or c.get('lot_number')),
        )
    except Exception as e:
        logger.exception("Error en BD al registrar el movimiento de gasto de cocina")
        return {
            'success': False,
            'message': 'No se pudo registrar el movimiento. Intenta de nuevo.',
        }

    return {'success': True, 'message': 'Acción procesada con éxito.'}