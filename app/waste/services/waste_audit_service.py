from app.waste.repositories.waste_audit_repository import WasteAuditRepository

class WasteAuditService:
    
    @staticmethod
    def get_formatted_audit_trail(user, filters):
        """Procesa la lógica de negocio y aplica las restricciones por rol."""
        location_ids = None
        
        # 1. Verificar roles globales usando las mismas propiedades del modelo User (is_admin, is_management, is_finance)
        is_admin = getattr(user, 'is_admin', False)
        is_management = getattr(user, 'is_management', False)
        is_finance = getattr(user, 'is_finance', False)
        
        # 2. Si NO es un rol global, filtramos por las sedes asignadas al usuario
        if not (is_admin or is_management or is_finance):
            if hasattr(user, 'assigned_locations') and user.assigned_locations:
                location_ids = [loc.id for loc in user.assigned_locations]
            else:
                location_ids = []  # Si no es admin ni tiene sedes asignadas, no ve registros

        # 3. Consultar los registros en la base de datos
        logs = WasteAuditRepository.get_audit_logs(
            location_ids=location_ids,
            start_date=filters.get('start_date'),
            end_date=filters.get('end_date'),
            severity=filters.get('severity')
        )
        
        # 4. Formatear la respuesta de forma segura frente a relaciones nulas
        formatted_logs = []
        for log in logs:
            changed_data = log.changed_data or {}
            # Obtener nombre de usuario de forma segura
            user_display = 'Sistema'
            if hasattr(log, 'user') and log.user:
                user_display = getattr(log.user, 'name', None) or getattr(log.user, 'email', None) or 'Sistema'
            if user_display == 'Sistema' and isinstance(changed_data, dict):
                user_display = changed_data.get('usuario') or changed_data.get('user') or changed_data.get('autor') or 'Sistema'

            # Obtener nombre de sede de forma segura
            location_display = 'General / Sede N/A'
            if hasattr(log, 'location') and log.location and hasattr(log.location, 'name'):
                location_display = log.location.name
            elif isinstance(changed_data, dict) and changed_data.get('location'):
                location_display = changed_data.get('location')

            # Extraer el Estado (Aprobado, Pendiente, Rechazado, Revertido) según la propuesta
            status_display = changed_data.get('status') or changed_data.get('estado') or 'APROBADO'

            # Formatear la fecha/hora a 12 Horas con AM/PM
            formatted_time = log.timestamp.strftime('%Y-%m-%d %I:%M:%S %p') if log.timestamp else ''

            formatted_logs.append({
                'id': log.id,
                'timestamp': formatted_time,
                'user': user_display,
                'location': location_display,
                'severity': log.severity,
                'status': status_display,
                'changed_data': changed_data
            })
            
        return formatted_logs