import json
from app.waste.repositories.waste_audit_repository import WasteAuditRepository
from app.models.waste_model import Waste, WasteType, WasteDetail
from app.models.inventory_model import Product

class WasteAuditService:
    
    @staticmethod
    def get_formatted_audit_trail(user, filters):
        """Procesa la lógica de negocio y aplica las restricciones por rol."""
        location_ids = None
        
        is_admin = getattr(user, 'is_admin', False)
        is_management = getattr(user, 'is_management', False)
        is_finance = getattr(user, 'is_finance', False)
        
        if not (is_admin or is_management or is_finance):
            if hasattr(user, 'locations') and user.locations:
                location_ids = [loc.id for loc in user.locations]
            else:
                location_ids = []

        logs = WasteAuditRepository.get_audit_logs(
            location_ids=location_ids,
            start_date=filters.get('start_date'),
            end_date=filters.get('end_date'),
            severity=filters.get('severity')
        )
        
        # 1. ORDENAMIENTO CRONOLÓGICO: Forzar que las mermas más recientes (mayor ID) vayan primero
        try:
            logs = sorted(logs, key=lambda x: getattr(x, 'id', 0) or 0, reverse=True)
        except Exception:
            pass

        # Caché local para optimizar consultas de BD
        product_cache = {}
        waste_type_cache = {}

        def resolve_product_name(product_id):
            if not product_id:
                return None
            try:
                pid = int(product_id)
                if pid not in product_cache:
                    p = Product.query.get(pid)
                    product_cache[pid] = p.name if p else None
                return product_cache[pid]
            except Exception:
                return None

        def resolve_waste_type_name(wt_id):
            if not wt_id:
                return None
            try:
                wpid = int(wt_id)
                if wpid not in waste_type_cache:
                    wt = WasteType.query.get(wpid)
                    waste_type_cache[wpid] = wt.name if wt else (wt.code if wt else None)
                return waste_type_cache[wpid]
            except Exception:
                return None

        formatted_logs = []
        for log in logs:
            raw_data = log.changed_data or {}
            
            if isinstance(raw_data, str):
                try:
                    changed_data = json.loads(raw_data)
                except Exception:
                    changed_data = {'detalle': raw_data}
            elif isinstance(raw_data, dict):
                changed_data = dict(raw_data)
            else:
                changed_data = {}

            # Responsable / Usuario
            user_display = 'Sistema'
            if hasattr(log, 'user') and log.user:
                user_display = getattr(log.user, 'name', None) or getattr(log.user, 'email', None) or 'Sistema'
            if user_display == 'Sistema':
                user_display = (
                    changed_data.get('usuario') or 
                    changed_data.get('user') or 
                    changed_data.get('autor') or 
                    changed_data.get('aprobado_por') or 
                    'Sistema'
                )

            # Sede
            location_display = 'General / Sede N/A'
            if hasattr(log, 'location') and log.location:
                location_display = (
                    getattr(log.location, 'nombre', None) or 
                    getattr(log.location, 'name', None) or 
                    str(log.location)
                )
            elif changed_data.get('location'):
                location_display = changed_data.get('location')
            elif changed_data.get('sede'):
                location_display = changed_data.get('sede')

            # Tipo de Merma
            tipo_merma_raw = (
                changed_data.get('tipo_merma') or 
                changed_data.get('tipo_de_merma') or 
                changed_data.get('waste_type') or 
                changed_data.get('waste_type_name') or 
                changed_data.get('tipo_merma_nombre') or 
                changed_data.get('tipo') or 
                changed_data.get('name')
            )

            waste_type_id = (
                changed_data.get('waste_type_id') or 
                changed_data.get('tipo_merma_id') or 
                changed_data.get('tipo_id')
            )

            tipo_merma = None
            if waste_type_id:
                tipo_merma = resolve_waste_type_name(waste_type_id)
            
            if not tipo_merma and tipo_merma_raw:
                if str(tipo_merma_raw).isdigit():
                    tipo_merma = resolve_waste_type_name(tipo_merma_raw)
                else:
                    tipo_merma = str(tipo_merma_raw)

            # Lista de productos mermados
            raw_products = (
                changed_data.get('productos') or 
                changed_data.get('detalles') or 
                changed_data.get('details') or 
                changed_data.get('items') or 
                changed_data.get('lineas') or 
                changed_data.get('lineas_detalles') or 
                changed_data.get('waste_details') or 
                changed_data.get('productos_afectados') or 
                changed_data.get('items_mermados') or 
                []
            )

            normalized_products = []
            if isinstance(raw_products, list):
                for item in raw_products:
                    if isinstance(item, dict):
                        p_id = item.get('product_id') or item.get('producto_id')
                        p_name = (
                            item.get('producto') or 
                            item.get('product_name') or 
                            item.get('product') or 
                            item.get('nombre') or 
                            item.get('nombre_producto') or 
                            item.get('producto_nombre') or 
                            item.get('descripcion')
                        )

                        if p_id and (not p_name or str(p_name).isdigit()):
                            db_pname = resolve_product_name(p_id)
                            if db_pname:
                                p_name = db_pname

                        if not p_name and p_id:
                            p_name = resolve_product_name(p_id)

                        if not p_name:
                            p_name = 'Producto'

                        p_lote = item.get('lote') or item.get('lot_number') or item.get('lot') or ''
                        p_cant = item.get('cantidad') or item.get('quantity') or item.get('qty') or 0
                        normalized_products.append({'producto': str(p_name), 'lote': str(p_lote), 'cantidad': p_cant})
                    elif isinstance(item, str):
                        normalized_products.append({'producto': item, 'lote': '', 'cantidad': 1})

            if not normalized_products:
                p_id = changed_data.get('product_id') or changed_data.get('producto_id')
                p_name = changed_data.get('producto') or changed_data.get('product_name') or changed_data.get('nombre_producto')
                
                if p_id and (not p_name or str(p_name).isdigit()):
                    p_name = resolve_product_name(p_id)

                if p_name:
                    p_lote = changed_data.get('lote') or changed_data.get('lot_number') or ''
                    p_cant = changed_data.get('cantidad') or changed_data.get('quantity') or changed_data.get('total_quantity') or 1
                    normalized_products.append({'producto': str(p_name), 'lote': str(p_lote), 'cantidad': p_cant})

            # 2. MOTIVO DE REGISTRO: Detección ampliada de claves
            motivo = (
                changed_data.get('motivo_registro') or 
                changed_data.get('motivo') or 
                changed_data.get('notes') or 
                changed_data.get('observacion') or 
                changed_data.get('observaciones') or 
                changed_data.get('description') or 
                changed_data.get('descripcion') or 
                changed_data.get('reason') or 
                changed_data.get('reversal_reason') or 
                changed_data.get('comentario') or 
                changed_data.get('comments')
            )

            # 3. EVIDENCIA FOTOGRÁFICA: Detección ampliada de claves
            foto_url = (
                changed_data.get('foto_evidencia_url') or 
                changed_data.get('evidence_url') or 
                changed_data.get('foto_url') or 
                changed_data.get('image_url') or 
                changed_data.get('evidence') or 
                changed_data.get('foto') or 
                changed_data.get('imagen') or 
                changed_data.get('file_path')
            )

            # Consulta directa al modelo Waste si faltan datos en el JSON
            # Consulta directa al modelo Waste si faltan datos en el JSON
            merma_id = changed_data.get('merma_id') or changed_data.get('waste_id') or changed_data.get('original_audit_id')
            if merma_id:
                try:
                    waste_obj = Waste.query.get(int(merma_id))
                    if waste_obj:
                        # ==================== AGREGAR AQUÍ ====================
                        # Sincronizar el estado real de la base de datos
                        if hasattr(waste_obj, 'status') and waste_obj.status:
                            if not changed_data.get('status') and not changed_data.get('estado'):
                                changed_data['status'] = waste_obj.status
                        # =======================================================

                        if (not tipo_merma or tipo_merma == 'No especificado') and hasattr(waste_obj, 'waste_type_id') and waste_obj.waste_type_id:
                            tipo_merma = resolve_waste_type_name(waste_obj.waste_type_id)
                        
                        if not normalized_products and hasattr(waste_obj, 'details') and waste_obj.details:
                            for d in waste_obj.details:
                                prod_name = resolve_product_name(d.product_id) or 'Producto'
                                normalized_products.append({
                                    'producto': prod_name,
                                    'lote': getattr(d, 'lot_number', '') or '',
                                    'cantidad': float(d.quantity) if getattr(d, 'quantity', None) else 0
                                })

                        if not motivo:
                            motivo = (
                                getattr(waste_obj, 'notes', None) or 
                                getattr(waste_obj, 'reason', None) or 
                                getattr(waste_obj, 'description', None) or 
                                getattr(waste_obj, 'observation', None)
                            )

                        if not foto_url:
                            foto_url = (
                                getattr(waste_obj, 'evidence_url', None) or 
                                getattr(waste_obj, 'image_url', None) or 
                                getattr(waste_obj, 'photo_url', None) or 
                                getattr(waste_obj, 'evidence', None)
                            )
                except Exception:
                    pass

            if not tipo_merma:
                tipo_merma = 'No especificado'

            if not motivo:
                motivo = 'Sin observación'

            # Normalización de la URL de la imagen (evita errores 404 por rutas relativas)
            if foto_url:
                foto_url = str(foto_url).strip()
                if foto_url and not foto_url.startswith(('http://', 'https://', '/')):
                    foto_url = '/' + foto_url

            formatted_time = log.timestamp.strftime('%Y-%m-%d %I:%M:%S %p') if getattr(log, 'timestamp', None) else 'N/A'

            # Actualizar diccionario formateado para Jinja2
            changed_data['tipo_merma'] = tipo_merma
            changed_data['productos'] = normalized_products
            changed_data['motivo_registro'] = motivo
            if foto_url:
                changed_data['foto_evidencia_url'] = foto_url
            changed_data['aprobado_por'] = changed_data.get('aprobado_por') or user_display

            status_display = (
                changed_data.get('status') or 
                changed_data.get('estado') or 
                changed_data.get('evento') or 
                'PENDIENTE'
            )

            formatted_logs.append({
                'id': log.id,
                'timestamp': formatted_time,
                'user': user_display,
                'location': location_display,
                'severity': getattr(log, 'severity', 'NORMAL'),
                'status': status_display,
                'changed_data': changed_data
            })
            
        return formatted_logs