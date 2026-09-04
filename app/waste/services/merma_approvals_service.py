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
from app.waste.repositories.merma_approvals_repository import MermaApprovalsRepository

# Tipos de evento de la auditoría de mermas (van dentro de changed_data['event'],
# nunca en audit_logs.action, que siempre es 'MERMA').
EV_APROBAR = 'MERMA_APROBADA'
EV_RECHAZAR = 'MERMA_RECHAZADA'
EV_CANCELAR = 'MERMA_CANCELADA'
EV_EDITAR = 'MERMA_EDITADA'

NOTIF_TIPO_APROBADA = 'MERMA_APROBADA'
NOTIF_TIPO_RECHAZADA = 'MERMA_RECHAZADA'

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
    if tasa > 0:
        esperado = round(tasa * dias, 2)
        umbral = round(esperado * tolerancia, 2)
        por_tiempo = registrado > umbral
    else:
        # Sin historial previo no hay base estadística para la regla de tiempo
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
    for r in rows:
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

    for r in rows:
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

    lines = []
    for d in items:
        stock_disponible = _stock_disponible(waste.location_id, d.product_id)
        qty = float(d.quantity)
        limite = prods.get(d.product_id, {}).get('waste_limit')
        lines.append({
            'product_id': d.product_id,
            'product_name': prods.get(d.product_id, {}).get('name') or f'Insumo #{d.product_id}',
            'lot_number': d.lot_number,
            'expiration_date': d.expiration_date.strftime('%d/%m/%Y') if d.expiration_date else 'Sin vencimiento',
            'quantity': qty,
            'unit_cost': float(d.unit_cost or 0),
            'subtotal_cost': float(d.subtotal_cost or 0),
            'stock_en_lote': stock_disponible,
            'waste_limit': limite,
            'unit': prods.get(d.product_id, {}).get('unit', ''),
            'excede_limite': (limite is not None) and (qty > limite),
        })

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
    return float(inv.current_quantity or 0)


def _descontar_stock(waste):
    """Descuenta current_quantity por producto/sede por cada línea de la merma.

    Valida que el stock alcance antes de descontar. Si algún producto no tiene
    suficiente stock se aborta (nada se descuenta; quien llama revierte).
    """
    cambios = []
    for d in waste.details:
        inv = MermaApprovalsRepository.get_inventory_item(waste.location_id, d.product_id)
        if inv is None:
            raise ValueError(
                f'No existe inventario para el insumo #{d.product_id} en la sede #{waste.location_id}.'
            )
        stock = float(inv.current_quantity or 0)
        qty = float(d.quantity or 0)
        if stock < qty:
            prod = Product.query.get(d.product_id)
            nombre = prod.name if prod else f'#{d.product_id}'
            raise ValueError(
                f'Stock insuficiente para {nombre}: disponible {stock:.2f}, merma {qty:.2f}.'
            )
        inv.current_quantity = round(stock - qty, 2)
        cambios.append({
            'product_id': d.product_id,
            'quantity': qty,
            'stock_antes': stock,
            'stock_despues': float(inv.current_quantity),
        })
    return cambios


def approve_waste(waste_id, user_id):
    """Admin aprueba una merma PENDIENTE: descuenta stock + audita + notifica."""
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

    try:
        cambios = _descontar_stock(waste)
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': str(exc)}

    try:
        MermaApprovalsRepository.mark_resolved(waste, user.id, 'APROBADO')
        MermaApprovalsRepository.create_audit(
            waste, user.id, EV_APROBAR, 'NORMAL',
            {
                'approved_by': user.name,
                'approved_by_id': user.id,
                'descuentos_stock': cambios,
                'total_quantity': float(waste.total_quantity or 0),
            },
        )
        _avisar_autor(waste, NOTIF_TIPO_APROBADA, 'aprobada', user)
        db.session.commit()
        return {'success': True, 'message': f'Merma #{waste.id} aprobada y stock descontado.'}
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': f'Error al aprobar la merma: {str(exc)}'}


def reject_waste(waste_id, user_id, reason):
    """Admin rechaza una merma PENDIENTE: no toca stock + audita + notifica."""
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

    try:
        MermaApprovalsRepository.mark_resolved(waste, user.id, 'RECHAZADO')
        MermaApprovalsRepository.create_audit(
            waste, user.id, EV_RECHAZAR, 'ALERTA',
            {
                'rejected_by': user.name,
                'rejected_by_id': user.id,
                'motivo_rechazo': (reason or '').strip(),
                'total_quantity': float(waste.total_quantity or 0),
            },
        )
        _avisar_autor(waste, NOTIF_TIPO_RECHAZADA, 'rechazada', user)
        db.session.commit()
        return {'success': True, 'message': f'Merma #{waste.id} rechazada (no se tocó el stock).'}
    except Exception as exc:
        db.session.rollback()
        return {'success': False, 'message': f'Error al rechazar la merma: {str(exc)}'}


def cancel_waste(waste_id, user_id, reason):
    """Retira una merma PENDIENTE antes de la respuesta del Admin.

    Pueden: el Admin, el autor y los usuarios de la sede de la merma. No toca
    stock (la pendiente nunca lo descontó): pasa a CANCELADA, se audita con el
    motivo y queda constancia en la Auditoría de Inventario.
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

    try:
        MermaApprovalsRepository.mark_cancelled(waste, user.id, reason)
        MermaApprovalsRepository.create_audit(
            waste, user.id, EV_CANCELAR, 'ALERTA',
            {
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


def _avisar_autor(waste, tipo, verbo, admin):
    """Notifica al autor de la merma que su merma fue aprobada o rechazada."""
    autor = MermaApprovalsRepository.get_user_by_id(waste.user_id)
    if not autor or autor.id == admin.id:
        return
    if Notification.query.filter_by(
        user_id=autor.id, type=tipo, waste_id=waste.id, is_read=False
    ).first():
        return
    db.session.add(Notification(
        user_id=autor.id,
        location_id=waste.location_id,
        waste_id=waste.id,
        type=tipo,
        message=f'Tu merma #{waste.id} fue {verbo} por el Administrador.',
        is_read=False,
    ))
