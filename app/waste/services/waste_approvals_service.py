"""Servicio de la bandeja de aprobaciones de mermas.

Contiene TODA la lógica de negocio: listar pendientes, ver detalle, aprobar
(descuenta stock + notifica + audita) y rechazar (no toca stock + notifica +
audita). Solo el Administrador aprueba/rechaza; el resto de roles (con cola de
pendientes) solo ve su bandeja en solo lectura.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.inventory_model import Product
from app.models.security_model import Notification
from app.waste.repositories.waste_approvals_repository import MermaApprovalsRepository

# Tipos de evento de la auditoría de mermas (van dentro de changed_data['event'],
# nunca en audit_logs.action, que siempre es 'MERMA').
EV_APROBAR = 'MERMA_APROBADA'
EV_RECHAZAR = 'MERMA_RECHAZADA'
EV_PARCIAL = 'MERMA_PARCIAL'        # Decisión final mixta: unos productos sí, otros no.
EV_DECISION = 'MERMA_DECISION'      # Batch de decisión mientras la merma sigue PENDIENTE.
EV_CANCELAR = 'MERMA_CANCELADA'
EV_EDITAR = 'MERMA_EDITADA'

NOTIF_TIPO_APROBADA = 'MERMA_APROBADA'
NOTIF_TIPO_RECHAZADA = 'MERMA_RECHAZADA'
NOTIF_TIPO_PARCIAL = 'MERMA_PARCIAL'

# Tipos que SIEMPRE requieren aprobación según la propuesta (regla de TIPO)
TIPOS_SENSIBLES = ('TEMPERATURA', 'ROBO_SOSPECHA')


def _param_text(clave, default):
    """Lee un parámetro de app_parameters con un valor por defecto."""
    params = MermaApprovalsRepository.get_app_parameters()
    try:
        return params.get(clave, default)
    except Exception:
        return default


def _param_float(clave, default):
    valor = _param_text(clave, default)
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float(default)


def _tasa_merma_diaria(location_id):
    """Mermas normales de la sede en los últimos 30 días promediadas por día."""
    hoy = datetime.now()
    since = hoy - timedelta(days=30)
    historial = MermaApprovalsRepository.get_merma_history(location_id, since)
    if not historial:
        return 0.0
    total = sum(h['total_quantity'] for h in historial)
    return total / 30.0


def _dias_desde_ultima_merma(waste_id, location_id):
    """Días transcurridos desde la última merma de la sede.

    Si no hay una merma previa real y separada, se aplica el período base
    configurado (regla de tiempo de la propuesta).
    """
    hoy = datetime.now()
    ultima = MermaApprovalsRepository.get_last_merma_date(location_id, waste_id)
    if ultima is None:
        return _param_float('WASTE_BASE_PERIOD_DAYS', 7)
    delta = (hoy - ultima).days
    if delta <= 0:
        return _param_float('WASTE_BASE_PERIOD_DAYS', 7)
    return delta


def _clasificar_novedad(waste_id, location_id, total_quantity, type_code, type_requires_approval):
    """Reconstruye el motivo (cantidad / tipo / tiempo) por el que una merma quedó pendiente.

    Devuelve el motivo de la novedad y, para la regla de tiempo, la comparación
    'registrado vs. esperado' usada por la bandeja.
    """
    motivos = []
    razones = []

    # -- Regla de TIPO: tipos que exigen aprobación siempre --
    code = type_code or ''
    if type_requires_approval or code in TIPOS_SENSIBLES:
        motivos.append('tipo')
        if code in ('TEMPERATURA', 'ROBO_SOSPECHA'):
            razones.append(f'{code} siempre requiere aprobación')
        else:
            razones.append('el tipo de merma exige aprobación')

    # -- Regla de CANTIDAD: alguna línea >= su límite de merma --
    lines = MermaApprovalsRepository.get_waste_lines([waste_id]).get(waste_id, [])
    prods = MermaApprovalsRepository.get_products_info({l['product_id'] for l in lines})
    excede = False
    for l in lines:
        limite = prods.get(l['product_id'], {}).get('waste_limit')
        if limite is not None and l['quantity'] >= limite:
            excede = True
            break
    if excede:
        motivos.append('cantidad')
        razones.append('alguna línea alcanzó o superó el límite de merma del producto')

    # -- Regla de TIEMPO: supera lo esperado en el período transcurrido --
    registrado = float(total_quantity or 0)
    tasa = _tasa_merma_diaria(location_id)
    dias = _dias_desde_ultima_merma(waste_id, location_id)
    tolerancia = _param_float('WASTE_TIME_TOLERANCE', 1.5)
    periodo_base = _param_float('WASTE_BASE_PERIOD_DAYS', 7)

    hoy = datetime.now()
    desde_30 = hoy - timedelta(days=30)
    fechas = [
        h['date'] for h in MermaApprovalsRepository.get_merma_history(
            location_id, desde_30)
        if h.get('date')
    ]
    history_days = max(0, (hoy - min(fechas)).days) if fechas else 0

    if tasa > 0 and history_days >= max(1.0, float(periodo_base)):
        esperado = round(tasa * dias, 2)
        umbral = round(esperado * tolerancia, 2)
        por_tiempo = registrado > umbral
    else:
        # Sin el período base de historial no hay base estadística para la regla de tiempo
        esperado = None
        umbral = None
        por_tiempo = False
    if por_tiempo:
        motivos.append('tiempo')
        razones.append('supera la merma esperada para el período transcurrido')

    if not motivos:
        motivos.append('info')
        razones.append('pendiente por configuración o revisión')

    return {
        'motivos': motivos,
        'razones': razones,
        'por_cantidad': 'cantidad' in motivos,
        'por_tipo': 'tipo' in motivos,
        'por_tiempo': por_tiempo,
        'registrado': registrado,
        'esperado': esperado,
        'umbral': umbral,
        'tasa_diaria': tasa,
        'dias_transcurridos': dias,
        'history_days': history_days,
        'tolerancia': tolerancia,
        'periodo_base': periodo_base,
    }


def get_pending_wastes(user_id):
    """Cola de mermas PENDIENTES que el usuario puede ver.

    Admin: todas. Resto: solo sus sedes asignadas (solo lectura).
    """
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user:
        return []
    rows = []
    if getattr(user, 'is_admin', False):
        rows = MermaApprovalsRepository.list_pending(None)
        # Un Admin no ve sus propias mermas: deben resolverlas otros admins
        rows = [r for r in rows if r.get('created_by') != user.id]
    else:
        loc_ids = [loc.id for loc in MermaApprovalsRepository.get_user_locations(user_id)]
        if not loc_ids:
            return []
        rows = MermaApprovalsRepository.list_pending(loc_ids)
    counts = MermaApprovalsRepository.get_detail_state_counts({r['id'] for r in rows})
    for r in rows:
        decididas, total = counts.get(r['id'], (0, 0))
        r['lineas_decididas'] = decididas
        r['lineas_total'] = total
        r['novelty'] = _clasificar_novedad(
            r['id'], r['location_id'], r['total_quantity'],
            r.get('type_code') or '', bool(r.get('type_requires_approval')),
        )
        r['es_autor'] = (r.get('created_by') == user.id)
        r['puede_resolver'] = getattr(user, 'is_admin', False) and (r.get('created_by') != user.id)
    return rows


def get_pending_waste_summary(user_id, limit=5):
    """Resumen en vivo de las mermas PENDIENTES visibles para el usuario.

    Admin: todas excepto las suyas. Resto de roles: sus sedes asignadas
    (solo lectura). Es ligero: no recalcula la clasificación de novedad.
    Alimenta el círculo rojo del sidebar junto a "Gestión de Mermas".
    """
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user:
        return {'pending_count': 0, 'items': []}
    rows = []
    if getattr(user, 'is_admin', False):
        rows = MermaApprovalsRepository.list_pending(None)
        rows = [r for r in rows if r.get('created_by') != user.id]
    else:
        loc_ids = [loc.id for loc in MermaApprovalsRepository.get_user_locations(user_id)]
        if not loc_ids:
            return {'pending_count': 0, 'items': []}
        rows = MermaApprovalsRepository.list_pending(loc_ids)
    rows = sorted(rows, key=lambda r: r.get('date') or datetime.min, reverse=True)
    items = [{
        'id': r['id'],
        'type_code': r.get('type_code') or '',
        'type_name': r.get('type_name') or 'Sin tipo',
        'location_name': r.get('location_name') or '',
        'author_name': r.get('author_name') or 'Desconocido',
        'total_quantity': r.get('total_quantity') or 0,
        'date': r['date'].isoformat() if r.get('date') else None,
    } for r in rows[:limit]]
    return {'pending_count': len(rows), 'items': items}


def _puede_gestionar_merma(user, waste):
    """¿El usuario puede editar/cancelar esta merma PENDIENTE?

    Pueden: cualquier Admin (todas las sedes), el autor y todo el que
    pertenezca a la sede de la merma."""
    if getattr(user, 'is_admin', False):
        return True
    if waste.user_id == user.id:
        return True
    locs = {loc.id for loc in MermaApprovalsRepository.get_user_locations(user.id)}
    return waste.location_id in locs


def get_pending_wastes_for_view(user_id):
    """Mermas PENDIENTES visibles en el listado de corrección/retiro.

    Alcance: el Administrador ve todas las sedes; los demás roles ven solo sus
    sedes asignadas. Pueden editar/cancelar: los Admins, el autor de la merma y
    los usuarios que pertenecen a su sede.
    """
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user:
        return [], False
    is_admin = getattr(user, 'is_admin', False)

    allowed = {loc.id for loc in MermaApprovalsRepository.get_user_locations(user_id)}

    if is_admin:
        rows = MermaApprovalsRepository.list_pending(None)
    else:
        if allowed:
            rows = MermaApprovalsRepository.list_pending(list(allowed))
        else:
            # Sin sedes: solo sus propias mermas pendientes.
            rows = [r for r in MermaApprovalsRepository.list_pending(None) if r.get('created_by') == user.id]

    counts = MermaApprovalsRepository.get_detail_state_counts({r['id'] for r in rows})
    for r in rows:
        decididas, total = counts.get(r['id'], (0, 0))
        r['lineas_decididas'] = decididas
        r['lineas_total'] = total
        fecha = r.get('date')
        r['fecha_display'] = fecha.strftime('%d/%m/%Y %H:%M') if fecha else '—'
        es_autor = (r.get('created_by') == user.id)
        r['es_autor'] = es_autor
        puede = es_autor or is_admin or (r.get('location_id') in allowed)
        r['puede_editar'] = puede
        r['puede_cancelar'] = puede
    return rows, is_admin


def get_waste_detail(waste_id, user_id):
    """Cabecera + líneas (con lote, vencimiento, cantidad y stock del lote)."""
    row = MermaApprovalsRepository.get_waste_with_type(waste_id)
    if not row:
        return None, 'La merma no existe.'

    waste = row[0]
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user:
        return None, 'Usuario no encontrado.'
    if not getattr(user, 'is_admin', False):
        allowed = {loc.id for loc in MermaApprovalsRepository.get_user_locations(user_id)}
        if waste.location_id not in allowed:
            return None, 'No tiene permisos para ver mermas de esta sede.'
    elif waste.user_id == user.id:
        return None, 'No puede resolver una merma que usted mismo registró. Debe resolverla otro administrador.'

    items = MermaApprovalsRepository.get_details_by_waste(waste_id)
    prods = MermaApprovalsRepository.get_products_info({d.product_id for d in items})
    resolved_ids = {d.resolved_by_id for d in items if d.resolved_by_id}
    resolvers = MermaApprovalsRepository.get_users(resolved_ids)

    lines = []
    for d in items:
        stock_disponible = _stock_disponible(waste.location_id, d.product_id)
        qty = float(d.quantity)
        limite = prods.get(d.product_id, {}).get('waste_limit')
        d_type = d.waste_type or (getattr(d, 'waste', None) and d.waste.waste_type) or None
        lines.append({
            'detail_id': d.id,
            'product_id': d.product_id,
            'product_name': prods.get(d.product_id, {}).get('name') or f'Insumo #{d.product_id}',
            'lot_number': d.lot_number,
            'expiration_date': d.expiration_date.strftime('%d/%m/%Y') if d.expiration_date else 'Sin vencimiento',
            'quantity': qty,
            'unit_cost': float(d.unit_cost or 0),
            'subtotal_cost': float(d.subtotal_cost or 0),
            'stock_en_lote': stock_disponible,
            'waste_limit': limite,
            'waste_type_id': d.waste_type_id or waste.waste_type_id,
            'waste_type_name': d_type.name if d_type else row.type_name,
            'waste_type_code': getattr(d_type, 'code', None) or row.type_code,
            'unit': prods.get(d.product_id, {}).get('unit', ''),
            'excede_limite': (limite is not None) and (qty > limite),
            'status': d.status or 'PENDIENTE',
            'resolved_by': resolvers.get(d.resolved_by_id) or '',
            'resolved_at': d.resolved_at.isoformat() if d.resolved_at else None,
            'resolution_reason': d.resolution_reason or '',
            'evidence_url': d.evidence_url or '',
        })

    decididas = sum(1 for ln in lines if ln['status'] != 'PENDIENTE')
    return {
        'id': waste.id,
        'location_name': row.location_name,
        'location_id': waste.location_id,
        'type_name': row.type_name,
        'type_code': row.type_code,
        'type_requires_approval': bool(row.type_requires_approval),
        'status': waste.status,
        'notes': waste.notes or '',
        'evidence_url': waste.evidence_url,
        'date': waste.date,
        'author_name': row.author_name,
        'created_by': waste.user_id,
        'es_autor': (waste.user_id == user.id),
        'puede_resolver': getattr(user, 'is_admin', False) and (waste.user_id != user.id),
        'total_quantity': float(waste.total_quantity or 0),
        'lineas_decididas': decididas,
        'lineas_total': len(lines),
        'novelty': _clasificar_novedad(
            waste.id, waste.location_id, float(waste.total_quantity or 0),
            row.type_code or '', bool(row.type_requires_approval),
        ),
        'lines': lines,
    }, None


def _only_admin(user_id):
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user or not getattr(user, 'is_admin', False):
        raise PermissionError('Solo el Administrador puede aprobar o rechazar mermas.')
    return user


def _stock_disponible(location_id, product_id):
    inv = MermaApprovalsRepository.get_inventory_item(location_id, product_id)
    if inv is None:
        return 0.0
    disponible = (
        float(inv.current_quantity or 0)
        - float(inv.transit_quantity or 0)
        - float(inv.reserved_quantity or 0)
    )
    return round(disponible, 2)


def _descontar_stock_lines(waste, details):
    """Descuenta current_quantity por producto/sede por cada línea a aprobar.

    Valida que el stock disponible (current - transit - reserved) alcance ANTES
    de descontar (de forma acumulada cuando varias líneas de la misma sede
    apuntan al mismo insumo). Si algún producto no tiene suficiente stock se
    aborta: nada se descuenta. Al aprobar se LIBERA la reserva correspondiente
    (el stock congelado que la merma pendiente había apartado).

    La auditoría registra el saldo físicamente contable (current_quantity)
    ANTES y DESPUÉS del descuento, no el "disponible", para que el historial
    muestre la transición real del inventario.
    """
    cambios = []
    saldos = {}
    for d in details:
        inv = MermaApprovalsRepository.get_inventory_item(waste.location_id, d.product_id)
        if inv is None:
            raise ValueError(
                f'No existe inventario para el insumo #{d.product_id} en la sede #{waste.location_id}.'
            )
        disponible = (
            float(inv.current_quantity or 0)
            - float(inv.transit_quantity or 0)
            - float(inv.reserved_quantity or 0)
        )
        saldo = saldos.get(d.product_id, disponible)
        qty = float(d.quantity or 0)
        if saldo < qty:
            prod = Product.query.get(d.product_id)
            nombre = prod.name if prod else f'#{d.product_id}'
            raise ValueError(
                f'Stock insuficiente para {nombre}: disponible {saldo:.2f}, merma {qty:.2f}.'
            )
        saldos[d.product_id] = saldo - qty
        cambios.append({
            'product_id': d.product_id,
            'quantity': qty,
            'stock_antes': None,
            'stock_despues': None,
        })
    # Aplicar los descuentos una vez validado todo y liberar la reserva,
    # registrando por línea el stock contable real antes/después.
    for d in details:
        inv = MermaApprovalsRepository.get_inventory_item(waste.location_id, d.product_id)
        antes = float(inv.current_quantity or 0)
        qty = float(d.quantity or 0)
        inv.current_quantity = round(antes - qty, 2)
        inv.reserved_quantity = round(
            max(0.0, float(inv.reserved_quantity or 0) - qty), 2
        )
        for c in cambios:
            if (
                c['product_id'] == d.product_id
                and c['quantity'] == qty
                and c['stock_antes'] is None
            ):
                c['stock_antes'] = antes
                c['stock_despues'] = round(antes - qty, 2)
                break
    return cambios


def _productos_name(ids):
    """Mapa {product_id: nombre} para los payloads de auditoría."""
    prods = MermaApprovalsRepository.get_products_info(ids)
    return {pid: info.get('name', f'#{pid}') for pid, info in prods.items()}


def decidir_lineas(waste_id, user_id, decisiones):
    """Aplica la decisión POR PRODUCTO a una merma pendiente.

    decisiones: lista de {detail_id, decision: 'aprobar'|'rechazar', reason?}
    - aprobar: descuenta el stock de esa línea y la marca APROBADO.
    - rechazar: no toca stock, exige motivo y la marca RECHAZADO.

    Mientras queden líneas PENDIENTES la cabecera sigue PENDIENTE (el Admin
    puede reabrir la merma). Al decidirse la última línea, la cabecera pasa a
    APROBADO / RECHAZADO / APROBADO_PARCIAL y se notifica al autor una sola vez
    con el resumen. Cada batch escribe una auditoría con el detalle por línea.
    """
    user = _only_admin(user_id)
    waste = MermaApprovalsRepository.get_waste_by_id(waste_id)
    if not waste:
        return {'success': False, 'message': 'La merma no existe.'}
    if waste.status != 'PENDIENTE':
        return {
            'success': False,
            'message': f'Solo se pueden decidir mermas pendientes (estado actual: {waste.status}).',
        }
    if waste.user_id == user.id:
        return {
            'success': False,
            'message': 'No puede decidir una merma que usted mismo registró. Debe resolverla otro administrador.',
        }

    detalle = {d.id: d for d in waste.details}
    aprobar = []
    rechazar = []
    usados = set()
    for dec in decisiones:
        try:
            detail_id = int(dec.get('detail_id'))
        except (TypeError, ValueError):
            return {'success': False, 'message': 'Identificador de línea inválido.'}
        if detail_id in usados:
            continue
        usados.add(detail_id)
        d = detalle.get(detail_id)
        if not d:
            return {'success': False, 'message': f'La línea #{detail_id} no pertenece a la merma #{waste_id}.'}
        if d.status != 'PENDIENTE':
            return {
                'success': False,
                'message': f'El producto de la línea #{detail_id} ya fue decidido ({d.status}).',
            }
        if dec.get('decision') == 'aprobar':
            aprobar.append(d)
        elif dec.get('decision') == 'rechazar':
            rechazar.append((d, (dec.get('reason') or '').strip()))
        else:
            return {'success': False, 'message': f'Decisión inválida en la línea #{detail_id}.'}

    if not aprobar and not rechazar:
        return {'success': False, 'message': 'No hay líneas pendientes por decidir en esta merma.'}

    for _d, reason in rechazar:
        if len(reason) < 15:
            return {
                'success': False,
                'message': 'El motivo de rechazo de cada producto debe tener al menos 15 caracteres.',
            }

    try:
        cambios = _descontar_stock_lines(waste, aprobar) if aprobar else []
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': str(exc)}

    # Al RECHAZAR una línea pendiente se libera su reserva: el stock congelado
    # por esta merma vuelve a estar disponible (current_quantity no se descuenta).
    for d, _reason in rechazar:
        inv = MermaApprovalsRepository.get_inventory_item(waste.location_id, d.product_id)
        if inv is None:
            continue
        inv.reserved_quantity = round(
            max(0.0, float(inv.reserved_quantity or 0) - float(d.quantity or 0)), 2
        )

    for d in aprobar:
        MermaApprovalsRepository.mark_line_resolved(d, user.id, 'aprobar')
    for d, reason in rechazar:
        MermaApprovalsRepository.mark_line_resolved(d, user.id, 'rechazar', reason)

    pendientes = [d for d in detalle.values() if (d.status or 'PENDIENTE') == 'PENDIENTE']
    finalizado = not pendientes

    if finalizado:
        todas_aprobadas = all(d.status == 'APROBADO' for d in detalle.values())
        todas_rechazadas = all(d.status == 'RECHAZADO' for d in detalle.values())
        if todas_aprobadas:
            estado_final = 'APROBADO'
        elif todas_rechazadas:
            estado_final = 'RECHAZADO'
        else:
            estado_final = 'APROBADO_PARCIAL'
        MermaApprovalsRepository.mark_resolved(waste, user.id, estado_final)

    # --- Auditoría del batch con detalle por línea ---
    nombres = _productos_name({d.product_id for d in aprobar} | {d.product_id for d, _reason in rechazar})
    decisiones_audit = []
    for d in aprobar:
        cambio = next(c for c in cambios if c['product_id'] == d.product_id and c['quantity'] == float(d.quantity or 0))
        decisiones_audit.append({
            'detail_id': d.id,
            'product_id': d.product_id,
            'product_name': nombres.get(d.product_id, f'#{d.product_id}'),
            'lot': d.lot_number or 'N/A',
            'quantity': float(d.quantity or 0),
            'decision': 'APROBADO',
            'motivo': '',
            'evidence_url': d.evidence_url or '',
            'stock_antes': cambio['stock_antes'],
            'stock_despues': cambio['stock_despues'],
        })
    for d, reason in rechazar:
        decisiones_audit.append({
            'detail_id': d.id,
            'product_id': d.product_id,
            'product_name': nombres.get(d.product_id, f'#{d.product_id}'),
            'lot': d.lot_number or 'N/A',
            'quantity': float(d.quantity or 0),
            'decision': 'RECHAZADO',
            'motivo': reason or '',
            'evidence_url': d.evidence_url or '',
            'stock_antes': None,
            'stock_despues': None,
        })

    motivos_rechazo = [reason for _d, reason in rechazar if reason and reason.strip()]

    if finalizado:
        event = EV_APROBAR if estado_final == 'APROBADO' else \
            (EV_RECHAZAR if estado_final == 'RECHAZADO' else EV_PARCIAL)
    else:
        event = EV_DECISION
    severity = 'ALERTA' if rechazar else 'NORMAL'

    MermaApprovalsRepository.create_audit(
        waste, user.id, event, severity,
        {
            'merma_id': waste.id,
            'resolved_by': user.name,
            'resolved_by_id': user.id,
            'decisiones': decisiones_audit,
            'descuentos_stock': cambios,
            'productos': [
                {
                    'producto': x['product_name'],
                    'lote': x['lot'],
                    'cantidad': x['quantity'],
                    'decision': x['decision'],
                    'motivo': x['motivo'],
                    'foto': x.get('evidence_url') or '',
                }
                for x in decisiones_audit
            ],
            **({'motivo_rechazo': ' | '.join(motivos_rechazo)} if motivos_rechazo else {}),
            'decididas': sum(1 for x in decisiones_audit if x['decision'] == 'APROBADO'),
            'rechazadas': sum(1 for x in decisiones_audit if x['decision'] == 'RECHAZADO'),
            'total_quantity': float(waste.total_quantity or 0),
            'finalizado': finalizado,
        },
    )

    if finalizado:
        _avisar_autor_final(waste, user, decisiones_audit)
        db.session.commit()
        resumen = {
            'a': sum(1 for x in decisiones_audit if x['decision'] == 'APROBADO'),
            'r': sum(1 for x in decisiones_audit if x['decision'] == 'RECHAZADO'),
        }
        if estado_final == 'APROBADO':
            return {'success': True, 'message': f'Merma #{waste.id} aprobada y stock descontado.', 'finalizado': True}
        if estado_final == 'RECHAZADO':
            return {'success': True, 'message': f'Merma #{waste.id} rechazada (no se tocó el stock).', 'finalizado': True}
        return {
            'success': True,
            'message': f'Merma #{waste.id} resuelta: {resumen["a"]} producto(s) aprobado(s) y {resumen["r"]} rechazado(s).',
            'finalizado': True,
        }

    db.session.commit()
    return {
        'success': True,
        'message': f'Decisión guardada ({len(decisiones_audit)} producto(s)). La merma sigue pendiente con {len(pendientes)} línea(s) por decidir.',
        'finalizado': False,
    }


def approve_waste(waste_id, user_id):
    """Admin aprueba TODAS las líneas pendientes de una merma: descuenta stock."""
    user = _only_admin(user_id)
    waste = MermaApprovalsRepository.get_waste_by_id(waste_id)
    if not waste:
        return {'success': False, 'message': 'La merma no existe.'}
    if waste.status != 'PENDIENTE':
        return {
            'success': False,
            'message': f'Solo se pueden aprobar mermas pendientes (estado actual: {waste.status}).',
        }
    if waste.user_id == user.id:
        return {
            'success': False,
            'message': 'No puede aprobar una merma que usted mismo registró. Debe resolverla otro administrador.',
        }
    pendientes = [d for d in waste.details if (d.status or 'PENDIENTE') == 'PENDIENTE']
    if not pendientes:
        return {'success': False, 'message': 'No hay líneas pendientes por aprobar en esta merma.'}
    decisiones = [{'detail_id': d.id, 'decision': 'aprobar'} for d in pendientes]
    return decidir_lineas(waste_id, user_id, decisiones)


def reject_waste(waste_id, user_id, reason):
    """Admin rechaza TODAS las líneas pendientes de una merma: no toca stock."""
    user = _only_admin(user_id)
    waste = MermaApprovalsRepository.get_waste_by_id(waste_id)
    if not waste:
        return {'success': False, 'message': 'La merma no existe.'}
    if waste.status != 'PENDIENTE':
        return {
            'success': False,
            'message': f'Solo se pueden rechazar mermas pendientes (estado actual: {waste.status}).',
        }
    if waste.user_id == user.id:
        return {
            'success': False,
            'message': 'No puede rechazar una merma que usted mismo registró. Debe resolverla otro administrador.',
        }
    pendientes = [d for d in waste.details if (d.status or 'PENDIENTE') == 'PENDIENTE']
    if not pendientes:
        return {'success': False, 'message': 'No hay líneas pendientes por rechazar en esta merma.'}
    decisiones = [{'detail_id': d.id, 'decision': 'rechazar', 'reason': reason} for d in pendientes]
    return decidir_lineas(waste_id, user_id, decisiones)


def cancel_waste(waste_id, user_id, reason):
    """Retira una merma PENDIENTE antes de la respuesta del Admin.

    Pueden: el Admin, el autor y los usuarios de la sede de la merma. No
    descuenta current_quantity (la pendiente nunca lo descontó): libera la
    reserva congelada (reserved_quantity), pasa a CANCELADA, se audita con el
    motivo y queda constancia en la Auditoría de Inventario. Si ya hay líneas
    decididas no se puede cancelar (parte del stock ya fue descontada).
    """
    user = MermaApprovalsRepository.get_user_by_id(user_id)
    if not user:
        return {'success': False, 'message': 'Usuario no encontrado.'}
    waste = MermaApprovalsRepository.get_waste_by_id(waste_id)
    if not waste:
        return {'success': False, 'message': 'La merma no existe.'}
    if waste.status != 'PENDIENTE':
        return {
            'success': False,
            'message': f'Solo se pueden cancelar mermas pendientes de respuesta (estado actual: {waste.status}).',
        }
    if not _puede_gestionar_merma(user, waste):
        return {
            'success': False,
            'message': 'Solo el Admin o usuarios de la sede de la merma pueden cancelarla.',
        }

    decididas = [d for d in waste.details if (d.status or 'PENDIENTE') != 'PENDIENTE']
    if decididas:
        return {
            'success': False,
            'message': 'No se puede cancelar: ya hay producto(s) decidido(s) en esta merma.',
        }

    try:
        # Se libera la reserva congelada por las líneas pendientes: el stock
        # vuelve a estar disponible (current_quantity no se descuenta).
        for d in waste.details:
            inv = MermaApprovalsRepository.get_inventory_item(waste.location_id, d.product_id)
            if inv is None:
                continue
            inv.reserved_quantity = round(
                max(0.0, float(inv.reserved_quantity or 0) - float(d.quantity or 0)), 2
            )
        MermaApprovalsRepository.mark_cancelled(waste, user.id, reason)
        MermaApprovalsRepository.create_audit(
            waste, user.id, EV_CANCELAR, 'ALERTA',
            {
                'merma_id': waste.id,
                'cancelled_by': user.name,
                'cancelled_by_id': user.id,
                'motivo_cancelacion': (reason or '').strip(),
                'total_quantity': float(waste.total_quantity or 0),
            },
        )
        db.session.commit()
        return {'success': True, 'message': f'Merma #{waste.id} cancelada (no se tocó el stock).'}
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': f'Error al cancelar la merma: {str(exc)}'}


def _avisar_autor_final(waste, admin, decisiones_audit):
    """Notifica al autor UNA Vez cuando TODAS las líneas están decididas.

    La notificación resume la decisión por producto: aprobadas/rechazadas.
    """
    autor = MermaApprovalsRepository.get_user_by_id(waste.user_id)
    if not autor or autor.id == admin.id:
        return
    # Cuenta REAL de la merma completa, no solo del batch actual: en una decisión
    # parcial previa ya pudieron quedar líneas APROBADAS/RECHAZADAS.
    todas = waste.details
    aprobadas = sum(1 for x in todas if (x.status or '') == 'APROBADO')
    rechazadas = sum(1 for x in todas if (x.status or '') == 'RECHAZADO')
    if rechazadas == 0:
        tipo = NOTIF_TIPO_APROBADA
        mensaje = f'Tu merma #{waste.id} fue aprobada ({aprobadas} producto(s), stock descontado).'
    elif aprobadas == 0:
        tipo = NOTIF_TIPO_RECHAZADA
        mensaje = f'Tu merma #{waste.id} fue rechazada ({rechazadas} producto(s)).'
    else:
        tipo = NOTIF_TIPO_PARCIAL
        mensaje = (
            f'Tu merma #{waste.id} fue resuelta parcialmente: '
            f'{aprobadas} aprobado(s) y {rechazadas} rechazado(s).'
        )
    if Notification.query.filter_by(
        user_id=autor.id, type=tipo, waste_id=waste.id, is_read=False
    ).first():
        return
    db.session.add(Notification(
        user_id=autor.id,
        location_id=waste.location_id,
        waste_id=waste.id,
        type=tipo,
        message=mensaje,
        is_read=False,
        created_at=datetime.now(),
    ))
