from app.waste.repositories.auditinventory_repository import AuditInventoryRepository
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

def process_inventory_action(log_id, current_user, action_type, new_quantity_requested=None, justification_notes=""):
    original_log_tuple = AuditInventoryRepository.get_audit_log_by_id(log_id)
    if not original_log_tuple:
        return {'success': False, 'message': 'El registro de auditoría solicitado no existe.'}
    
    location_id = original_log_tuple.location_id
    action_name_upper = original_log_tuple.action.upper()

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
        final_notes = f"Edición del log #{log_id} (Gasto original: {abs_original}, Nuevo gasto: {abs(new_requested_dec)}). Motivo: {justification_notes}"
        new_severity_status = 'EDITADO'
    else:
        return {'success': False, 'message': 'Acción no reconocida.'}

    if required_adjustment < Decimal('0') and current_stock < abs(required_adjustment):
        return {
            'success': False, 
            'message': f'Imposible procesar. Stock insuficiente (Disponible: {current_stock}, Requerido: {abs(required_adjustment)}).'
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
            new_original_severity=new_severity_status
        )
    except Exception as e:
        return {'success': False, 'message': f'Error en base de datos al registrar el movimiento: {str(e)}'}

    return {'success': True, 'message': 'Acción procesada con éxito.'}