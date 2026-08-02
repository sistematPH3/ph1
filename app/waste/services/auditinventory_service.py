from app.waste.repositories.auditinventory_repository import AuditInventoryRepository

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
    
    formatted_logs = []
    for log in raw_logs:
        changed_data = log.changed_data or {}
        
        # Extraemos la variación
        qty_changed = float(changed_data.get('quantity_changed', 0))
        
        # Función auxiliar para limpiar y convertir a float seguro
        def safe_float(val):
            if val in (None, ''):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        prev_qty = safe_float(changed_data.get('previous_quantity'))
        new_qty = safe_float(changed_data.get('new_quantity'))

        # --- LÓGICA MATEMÁTICA AGRESIVA PARA CORREGIR DATOS ---
        if qty_changed != 0:
            # CASO A: Consumo (Gasto, Merma, Cocina, etc) -> Negativo (Ej: -20.0)
            if qty_changed < 0:
                # Si el stock anterior dice 0 (imposible consumir de 0) o no existe,
                # inferimos que había suficiente stock antes y tras el gasto llegó a new_qty (o 0 si no se especificó)
                if prev_qty in (0, 0.0, None):
                    if new_qty is not None and new_qty > 0:
                        prev_qty = new_qty - qty_changed  # new_qty + abs(qty_changed)
                    else:
                        prev_qty = abs(qty_changed)
                        new_qty = 0.0
                elif new_qty is None:
                    new_qty = prev_qty + qty_changed

            # CASO B: Reabastecimiento -> Positivo (Ej: +20.0)
            elif qty_changed > 0:
                # Si ambos dicen 0 o no existen, inferimos que partió de cero
                if prev_qty in (0, 0.0, None) and new_qty in (0, 0.0, None):
                    prev_qty = 0.0
                    new_qty = qty_changed
                elif new_qty is None and prev_qty is not None:
                    new_qty = prev_qty + qty_changed
                elif prev_qty is None and new_qty is not None:
                    prev_qty = new_qty - qty_changed

        # Protección final: si por alguna razón siguen siendo None, los pasamos a 0.0
        if prev_qty is None: prev_qty = 0.0
        if new_qty is None: new_qty = 0.0

        # Evitar mostrar stocks negativos irreales en el historial
        if prev_qty < 0: prev_qty = 0.0
        if new_qty < 0: new_qty = 0.0

        formatted_logs.append({
            'id': log.id,
            'action': log.action,
            'severity': log.severity,
            'user_name': log.user_name,
            'location_name': log.location_name or changed_data.get('location_name', 'Almacén Principal'),
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else 'N/A',
            'product_name': changed_data.get('product_name', 'N/A'),
            'previous_quantity': prev_qty,
            'new_quantity': new_qty,
            'quantity_changed': qty_changed,
            'notes': changed_data.get('notes', '')
        })
        
    return formatted_logs