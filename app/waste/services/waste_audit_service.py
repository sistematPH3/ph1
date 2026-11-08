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
        
        # Ordenamiento cronológico (más recientes primero)
        try:
            logs = sorted(logs, key=lambda x: getattr(x, 'id', 0) or 0, reverse=True)
        except Exception:
            pass

        # Caché local para optimizar consultas de BD
        product_cache = {}
        waste_type_cache = {}
        product_unit_cache = {}

        def resolve_product_unit(product_id):
            if not product_id:
                return None
            try:
                pid = int(product_id)
                if pid not in product_unit_cache:
                    p = Product.query.get(pid)
                    product_unit_cache[pid] = getattr(p, 'unit_of_measure', None) if p else None
                return product_unit_cache[pid]
            except Exception:
                return None

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

        def _resolve_decision_motivo(item):
            # Las decisiones de aprobación/rechazo guardan detail_id (id de la
            # línea WasteDetail); de ahí sale el motivo real de cada línea.
            if not isinstance(item, dict):
                return ''
            mt = str(item.get('motivo_tipo') or item.get('waste_type_name') or '').strip()
            if mt:
                return mt
            did = item.get('detail_id')
            if did:
                try:
                    det = WasteDetail.query.get(int(did))
                except (TypeError, ValueError):
                    det = None
                if det and getattr(det, 'waste_type_id', None):
                    return resolve_waste_type_name(det.waste_type_id) or ''
            return ''

        # Acciones para mapear cada evento
        REVERT_ACTIONS = {'REVERSION', 'REVERTIDO', 'REVERTIDA', 'ANULACION', 'ANULADO', 'REVERTIR', 'REVERT', 'CANCELADO', 'CANCELAR', 'MERMA_CANCELADA'}
        REJECT_ACTIONS = {'RECHAZO', 'RECHAZADO', 'RECHAZADA', 'RECHAZAR', 'REJECT', 'REJECTED', 'MERMA_RECHAZADA'}
        APPROVE_ACTIONS = {'APROBACION', 'APROBADO', 'APROBADA', 'APROBAR', 'APPROVE', 'APPROVED', 'MERMA_APROBADA'}
        MERMA_PARTIAL_ACTIONS = {'MERMA_PARCIAL', 'MERMA_DECISION', 'APROBADO_PARCIAL'}
        PENDING_ACTIONS = {
            'CREACION', 'CREAR', 'CREADO', 'NUEVO', 'REGISTRO', 'REGISTRADO', 'CREATE', 'INSERT',
            'EDICION', 'EDITADO', 'EDITADA', 'CORRECCION', 'CORREGIDO', 'EDIT', 'UPDATE', 'ACTUALIZADO', 'ACTUALIZACION', 'PENDIENTE',
            'MERMA_EDITADA', 'MERMA_EDITADO'
        }

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
                    changed_data.get('rechazado_por') or
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
            before_state = changed_data.get('before')
            after_state = changed_data.get('after')
            is_edit_event = (
                isinstance(before_state, dict)
                and isinstance(after_state, dict)
                and 'lines' in after_state
            )
            if is_edit_event:
                # Edición: cada línea del DESPUÉS con su antes → después
                # (producto, lote, cantidad y motivo) para evidenciar el cambio real.
                # Las líneas PENDIENTES se emparejan por orden (la edición las
                # reemplaza en el mismo orden); las ya decididas se conservan iguales.
                before_lines = (before_state.get('lines') or []) if isinstance(before_state, dict) else []
                after_lines = (after_state.get('lines') or []) if isinstance(after_state, dict) else []

                def _st(line):
                    st = line.get('status')
                    return ('' if st is None else str(st) or 'PENDIENTE').upper()

                before_pending = [b for b in before_lines if isinstance(b, dict) and _st(b) == 'PENDIENTE']
                after_pending = [a for a in after_lines if isinstance(a, dict) and _st(a) == 'PENDIENTE']
                after_decididas = [a for a in after_lines if isinstance(a, dict) and _st(a) != 'PENDIENTE']

                combined = []
                for idx, item in enumerate(after_pending):
                    before_item = before_pending[idx] if idx < len(before_pending) else {}
                    combined.append((item, before_item))
                for item in after_decididas:
                    combined.append((item, dict(item)))

                for item, before_item in combined:
                    p_id = item.get('product_id')
                    p_name = resolve_product_name(p_id) or 'Producto'
                    wt_after = (
                        item.get('waste_type_id')
                        or before_state.get('waste_type_id')
                        or after_state.get('waste_type_id')
                    )
                    tipo_after = resolve_waste_type_name(wt_after) or ''

                    wt_before = before_item.get('waste_type_id')
                    tipo_before = resolve_waste_type_name(wt_before) or tipo_after

                    qty_after = item.get('quantity') or 0
                    qty_before = before_item.get('quantity')

                    cambio_motivo = bool(wt_before and wt_after and wt_before != wt_after)
                    cambio_cantidad = False
                    if qty_before is not None:
                        try:
                            cambio_cantidad = float(qty_before) != float(qty_after)
                        except (TypeError, ValueError):
                            cambio_cantidad = False

                    normalized_products.append({
                        'producto': str(p_name),
                        'lote': str(item.get('lot_number') or ''),
                        'cantidad': qty_after,
                        'cantidad_antes': qty_before,
                        'cambio_cantidad': cambio_cantidad,
                        'motivo_tipo': tipo_after,
                        'motivo_tipo_antes': tipo_before,
                        'cambio_motivo': cambio_motivo,
                        'unidad': resolve_product_unit(p_id),
                    })

            if is_edit_event:
                changed_data['es_edicion'] = True
                changed_data['evento'] = 'MERMA_EDITADA'
                changed_data['editado_por'] = user_display

            decisiones_raw = changed_data.get('decisiones')
            if isinstance(decisiones_raw, list) and decisiones_raw:
                for item in decisiones_raw:
                    if not isinstance(item, dict):
                        continue
                    p_id = item.get('product_id') or item.get('producto_id')
                    p_name = (
                        item.get('product_name') or
                        item.get('producto') or
                        item.get('product') or
                        item.get('nombre')
                    )
                    if p_id and (not p_name or str(p_name).isdigit()):
                        db_pname = resolve_product_name(p_id)
                        if db_pname:
                            p_name = db_pname
                    if not p_name:
                        p_name = 'Producto'
                    normalized_products.append({
                        'producto': str(p_name),
                        'lote': str(item.get('lot') or item.get('lote') or item.get('lot_number') or ''),
                        'cantidad': item.get('quantity') or item.get('cantidad') or 0,
                        'decision': item.get('decision') or '',
                        'motivo_tipo': _resolve_decision_motivo(item),
                        'motivo': item.get('motivo') or '',
                        'foto': item.get('evidence_url') or '',
                        'unidad': resolve_product_unit(p_id) or resolve_product_unit(item.get('producto_id')),
                    })
            elif isinstance(raw_products, list):
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
                        wt_id = item.get('waste_type_id') or item.get('motivo_id') or item.get('tipo_id')
                        motivo_tipo = (
                            item.get('motivo_tipo') or
                            item.get('waste_type_name') or
                            item.get('tipo_merma') or
                            ''
                        )
                        if not motivo_tipo and wt_id:
                            motivo_tipo = resolve_waste_type_name(wt_id) or ''
                        normalized_products.append({
                            'producto': str(p_name),
                            'lote': str(p_lote),
                            'cantidad': p_cant,
                            'motivo_tipo': motivo_tipo or '',
                            'foto': item.get('evidence_url') or item.get('foto') or item.get('photo_url') or '',
                            'unidad': resolve_product_unit(p_id),
                        })
                    elif isinstance(item, str):
                        normalized_products.append({'producto': item, 'lote': '', 'cantidad': 1})

            # Fallback: si el log no trae detalle por línea, intentar fuente única
            used_generic_fallback = False
            if not normalized_products:
                p_id = changed_data.get('product_id') or changed_data.get('producto_id')
                p_name = changed_data.get('producto') or changed_data.get('product_name') or changed_data.get('nombre_producto')
                
                if p_id and (not p_name or str(p_name).isdigit()):
                    p_name = resolve_product_name(p_id)

                if p_name:
                    p_lote = changed_data.get('lote') or changed_data.get('lot_number') or ''
                    p_cant = changed_data.get('cantidad') or changed_data.get('quantity') or changed_data.get('total_quantity')
                    used_generic_fallback = p_cant is None
                    normalized_products.append({
                        'producto': str(p_name),
                        'lote': str(p_lote),
                        'cantidad': p_cant if p_cant is not None else 1,
                        'unidad': resolve_product_unit(p_id),
                    })

            # Motivo de Registro
            motivo = (
                changed_data.get('motivo_registro') or 
                changed_data.get('motivo') or 
                changed_data.get('motivo_edicion') or 
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

            # Evidencia Fotográfica
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

            # Verificar si la merma matriz ya está revertida en la base de datos
            merma_id = changed_data.get('merma_id') or changed_data.get('waste_id') or changed_data.get('original_audit_id')
            is_reverted_in_db = False
            
            if merma_id:
                try:
                    waste_obj = Waste.query.get(int(merma_id))
                    if waste_obj:
                        st_obj = str(getattr(waste_obj, 'status', '')).upper().strip()
                        if st_obj in ['REVERTIDO', 'REVERTIDA', 'ANULADO', 'CANCELADO']:
                            is_reverted_in_db = True

                        if (not tipo_merma or tipo_merma == 'No especificado') and hasattr(waste_obj, 'waste_type_id') and waste_obj.waste_type_id:
                            tipo_merma = resolve_waste_type_name(waste_obj.waste_type_id)
                        
                        if (used_generic_fallback or not normalized_products) and hasattr(waste_obj, 'details') and waste_obj.details:
                            normalized_products = []
                            for d in waste_obj.details:
                                prod_name = resolve_product_name(d.product_id) or 'Producto'
                                motivo_tipo = ''
                                if getattr(d, 'waste_type_id', None):
                                    motivo_tipo = resolve_waste_type_name(d.waste_type_id) or ''
                                normalized_products.append({
                                    'producto': prod_name,
                                    'lote': getattr(d, 'lot_number', '') or '',
                                    'cantidad': float(d.quantity) if getattr(d, 'quantity', None) else 0,
                                    'motivo_tipo': motivo_tipo,
                                    'unidad': resolve_product_unit(d.product_id),
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

            # EVALUACIÓN DEL ESTADO HISTÓRICO DE ESTE LOG
            action_signals = []
            
            for attr in ['action', 'accion', 'event', 'evento', 'event_type', 'tipo_evento', 'operation', 'operacion', 'type', 'tipo']:
                val = getattr(log, attr, None)
                if val:
                    action_signals.append(str(val).upper().strip())

            for key in ['action', 'accion', 'event', 'evento', 'event_type', 'tipo_evento', 'operation', 'operacion', 'tipo_accion', 'nuevo_estado', 'estado_nuevo', 'new_status']:
                val = changed_data.get(key)
                if val:
                    action_signals.append(str(val).upper().strip())

            status_display = None
            for signal in action_signals:
                if signal in REVERT_ACTIONS:
                    status_display = 'REVERTIDO'
                    break
                elif signal in REJECT_ACTIONS:
                    status_display = 'RECHAZADO'
                    break
                elif signal in APPROVE_ACTIONS:
                    status_display = 'APROBADO'
                    break
                elif signal in MERMA_PARTIAL_ACTIONS:
                    status_display = 'APROBADO_PARCIAL'
                    break
                elif signal in PENDING_ACTIONS:
                    status_display = 'PENDIENTE'
                    break

            if not status_display:
                if any(changed_data.get(k) for k in ['motivo_reversion', 'reversal_reason', 'motivo_anulacion']):
                    status_display = 'REVERTIDO'
                elif any(changed_data.get(k) for k in ['motivo_rechazo', 'rejection_reason', 'rechazado_por']):
                    status_display = 'RECHAZADO'
                elif any(changed_data.get(k) for k in ['aprobado_por', 'approved_by', 'resolved_by']) and not any(changed_data.get(k) for k in ['motivo_rechazo', 'motivo_reversion']):
                    status_display = 'APROBADO'
                else:
                    status_display = 'PENDIENTE'

            # Es revertida si la merma ya está revertida en BD o si este log es una reversión
            is_reverted = is_reverted_in_db or (status_display == 'REVERTIDO')

            motivo_reversion = (
                changed_data.get('motivo_reversion') or 
                changed_data.get('reversal_reason') or 
                changed_data.get('motivo_anulacion')
            )
            if motivo_reversion:
                changed_data['motivo_reversion'] = motivo_reversion

            if not tipo_merma:
                tipo_merma = 'No especificado'

            if not motivo:
                motivo = 'Sin observación'

            if foto_url:
                foto_url = str(foto_url).strip()
                if foto_url and not foto_url.startswith(('http://', 'https://', '/')):
                    foto_url = '/' + foto_url

            # Cuando la evidencia es única (p. ej. una merma de una sola línea),
            # se adjunta a esa línea para que tenga su enlace de foto propio.
            if foto_url and len(normalized_products) == 1 and not normalized_products[0].get('foto'):
                normalized_products[0]['foto'] = foto_url

            formatted_time = log.timestamp.strftime('%Y-%m-%d %I:%M:%S %p') if getattr(log, 'timestamp', None) else 'N/A'

            changed_data['tipo_merma'] = tipo_merma
            changed_data['productos'] = normalized_products
            changed_data['motivo_registro'] = motivo
            if foto_url:
                changed_data['foto_evidencia_url'] = foto_url
            changed_data['aprobado_por'] = changed_data.get('aprobado_por') or user_display

            fotos = []
            for p in normalized_products:
                f = str(p.get('foto') or '').strip()
                if f:
                    fotos.append({'url': f, 'label': p.get('producto') or 'Producto'})
            if not fotos and foto_url:
                fotos.append({'url': foto_url, 'label': 'Evidencia general'})
            changed_data['fotos'] = fotos

            formatted_logs.append({
                'id': log.id,
                'timestamp': formatted_time,
                'user': user_display,
                'location': location_display,
                'severity': getattr(log, 'severity', 'NORMAL'),
                'status': status_display,
                'is_reverted': is_reverted,
                'changed_data': changed_data
            })
            
        return formatted_logs