import json
from datetime import datetime, time, timedelta

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import LoginAudit, Location, Role
from app.reports.repositories.export_repository import obtener_nombre_autor
from app.security.repositories.audit_user_repository import AuditUserRepository
from app.security.services.audit_purchase_service import AuditPurchaseService


def _rango_datetimes(desde, hasta):
    """Convierte fechas (date) del filtro en datetimes inclusive del día."""
    inicio = datetime.combine(desde, time.min) if desde else None
    fin = datetime.combine(hasta, time(23, 59, 59)) if hasta else None
    return inicio, fin


def _texto_rango(desde, hasta):
    fmt = '%d/%m/%Y'
    if desde and hasta:
        return f"del {desde.strftime(fmt)} al {hasta.strftime(fmt)}"
    if desde:
        return f"a partir del {desde.strftime(fmt)}"
    if hasta:
        return f"hasta el {hasta.strftime(fmt)}"
    return 'Todo el historial'


def _ts(valor):
    if not valor:
        return '—'
    return valor.strftime('%d/%m/%Y %I:%M:%S %p')


def _nombre_sede(sede_id):
    loc = db.session.get(Location, sede_id) if sede_id else None
    return loc.name if loc else (f'Sede #{sede_id}' if sede_id else None)


def _resolver_sede(valor):
    """Normaliza el filtro de sede recibido por URL.

    Devuelve una tupla (es_global, id_sede, nombre) donde solo un elemento
    es distinto de None: 'global' (sin sede), un id numérico o el nombre.
    """
    if not valor:
        return False, None, None
    v = str(valor).strip()
    if v.lower() == 'global':
        return True, None, None
    if v.isdigit():
        return False, int(v), None
    return False, None, v.lower()


def _buscar_sede_por_nombre(nombre_lower):
    """Resuelve un Location por nombre (insensible a mayúsculas)."""
    if not nombre_lower:
        return None
    return (Location.query
            .filter(db.func.lower(Location.name) == nombre_lower)
            .first())


def _detalles_cambiados(changed_data):
    """Convierte el dict de cambios (campo: {old, new}) en una línea de texto."""
    if not changed_data:
        return '—'
    return ' | '.join(_cambios_lista(changed_data))


def _cambios_lista(changed_data):
    """Devuelve la lista de cambios 'campo: old → new' para las tarjetas."""
    if not changed_data:
        return []
    partes = []
    for campo, valores in changed_data.items():
        if isinstance(valores, dict):
            old = valores.get('old', '')
            new = valores.get('new', '')
            partes.append(f"{campo}: {old} → {new}".replace('\n', ' '))
        else:
            partes.append(f"{campo}: {valores}")
    return partes


def _etiqueta_accion(accion):
    """Traduce el action_type a su etiqueta en español (mayúsc/minúsculas)."""
    return {
        'CREATE': 'Creación',
        'ANNULLED': 'Anulación',
        'EDIT': 'Edición',
        'UPDATE': 'Edición',
        'ACTIVATE': 'Activación',
        'DEACTIVATE': 'Inactivación',
        'DELETE': 'Eliminación',
        'LOGIN': 'Inicio de sesión',
        'LOGOUT': 'Cierre de sesión',
        'INICIO_SESION': 'Inicio de sesión',
        'CERRAR_SESION': 'Cierre de sesión',
        'PASSWORD': 'Cambio de contraseña',
        'ROLE': 'Cambio de rol',
    }.get((accion or '').upper(), accion or '—')


def _fmt_qty(valor):
    """Da formato a cantidades numéricas sin ceros finales."""
    try:
        return f"{float(valor):g}"
    except (TypeError, ValueError):
        return str(valor) if valor is not None else '0'


def _etiqueta_evento(evt):
    """Nombre legible de la acción del evento de traslado."""
    accion = (evt.action or '') if hasattr(evt, 'action') else ''
    return {
        'DESPACHO_EMISION': 'Despacho Emitido',
        'CANCELACION_PRE_SALIDA': 'Cancelado en Salida',
        'RECEPCION_CONFORME': 'Recepción Conforme',
        'RECEPCION_NOVEDAD': 'Recepción con Novedad',
        'RESOLUCION_DISPUTA': 'Resolución de Disputa',
    }.get(accion, accion.replace('_', ' ').title() or accion)


def _detalle_evento_traslado(evt):
    """Texto completo de un evento (ítems, cantidades, notas y stock)."""
    data = getattr(evt, 'changed_data', None) or {}
    accion = (evt.action or '') if hasattr(evt, 'action') else ''
    lineas = []

    if accion == 'DESPACHO_EMISION':
        items = data.get('items')
        if items:
            lineas.append('ÍTEMS DESPACHADOS:')
            for item in items:
                lineas.append(
                    f"  · {item.get('sku', 'N/A')} | "
                    f"{item.get('product_name', 'N/A')} | "
                    f"Lote: {item.get('lot_number', 'N/A')} | "
                    f"Venc: {item.get('expiration_date', 'N/A')} | "
                    f"Cant. despachada: {_fmt_qty(item.get('dispatched_qty', 0))}")
        else:
            lineas.append('ÍTEMS DESPACHADOS: Sin desglose de insumos.')
        si = data.get('stock_impact') or {}
        if si:
            lineas.append(
                f"  Stock: sale de origen {_fmt_qty(si.get('origin_current_delta', 0))} | "
                f"congelado en tránsito {_fmt_qty(si.get('origin_transit_delta', 0))}")

    elif accion == 'CANCELACION_PRE_SALIDA':
        lineas.append(f"MOTIVO: {data.get('reason', '—')}")
        si = data.get('stock_impact') or {}
        if si:
            lineas.append(
                f"  Stock: reintegrado al origen "
                f"{_fmt_qty(si.get('origin_current_delta', 0))} | "
                f"tránsito liberado {_fmt_qty(si.get('origin_transit_delta', 0))}")

    elif accion in ('RECEPCION_CONFORME', 'RECEPCION_NOVEDAD'):
        if data.get('notes'):
            lineas.append(f"NOTA: {data['notes']}")
        nt = data.get('novelty_type')
        if nt and nt != 'SIN_NOVEDAD':
            lineas.append(f"NOVEDAD: {str(nt).replace('_', ' ').title()}")
        items = data.get('items')
        if items:
            lineas.append('RECEPCIÓN DE ÍTEMS:')
            for item in items:
                recibida = item.get('received_qty', item.get('dispatched_qty', 0))
                faltante = item.get('missing_qty', 0)
                lineas.append(
                    f"  · {item.get('product_name', 'N/A')} | "
                    f"Lote: {item.get('lot_number', 'N/A')} | "
                    f"Despachada: {_fmt_qty(item.get('dispatched_qty', 0))} | "
                    f"Recibida: {_fmt_qty(recibida)} | "
                    f"Faltante: {_fmt_qty(faltante) if faltante > 0 else '-'} | "
                    f"Novedad: {str(item.get('specific_novelty', 'CONFORME')).replace('_', ' ').title()}")
        else:
            lineas.append('RECEPCIÓN DE ÍTEMS: Sin desglose de insumos.')
        for err in (data.get('erroneous_products_delivered') or []):
            lineas.append(
                f"  FUERA DE GUÍA: {err.get('product_name', 'N/A')} "
                f"(cant. {_fmt_qty(err.get('quantity_delivered', 0))})")

    elif accion == 'RESOLUCION_DISPUTA':
        summary = data.get('resolution_summary') or {}
        total_lost = summary.get('lost_total', 0) or 0
        if total_lost > 0:
            lineas.append(
                f"MERCADERÍA DE BAJA / EXTRAVIADA: {_fmt_qty(total_lost)} unidades.")
        if data.get('general_notes'):
            lineas.append(f"NOTA DE RESOLUCIÓN: {data['general_notes']}")
        items = data.get('items')
        if items:
            lineas.append('RESOLUCIÓN POR ÍTEM:')
            for item in items:
                lost = item.get('lost_qty', 0) or 0
                lineas.append(
                    f"  · Lote: {item.get('lot_number', 'N/A')} | "
                    f"Acción: {str(item.get('action', 'SIN_ACCION')).replace('_', ' ').title()} | "
                    f"Acreditado destino: {_fmt_qty(item.get('credited_qty', 0))} | "
                    f"Devuelto origen: {_fmt_qty(item.get('return_qty', 0))} | "
                    f"De baja/extraviado: {_fmt_qty(lost) if lost > 0 else '-'}")
        else:
            lineas.append('RESOLUCIÓN POR ÍTEM: Sin desglose.')
        if data.get('linked_return_movement_id'):
            lineas.append(
                f"RETORNO AUTOMÁTICO: id {data['linked_return_movement_id']}")

    else:
        texto = json.dumps(data, ensure_ascii=False, default=str)
        lineas.append(f"DATOS: {texto}" if texto and texto != '{}'
                      else 'Sin datos adicionales.')

    return '\n'.join(lineas)


def _etiqueta_sede_documento(user, filtros):
    es_global, sede_id, sede_nombre = _resolver_sede(filtros.get('sede'))
    if getattr(user, 'is_admin', False):
        if es_global:
            return 'Global / Sin Sede'
        if sede_id:
            return _nombre_sede(sede_id) or f'Sede #{sede_id}'
        if sede_nombre:
            loc = _buscar_sede_por_nombre(sede_nombre)
            return loc.name if loc else sede_nombre.title()
        return 'Todas las sedes'
    if getattr(user, 'is_finance', False):
        nombres = [loc.name for loc in user.locations if loc]
        return ', '.join(nombres) if nombres else 'Sin sedes asignadas'
    return 'Todas las sedes'


def _base(tipo, titulo, user, filtros, tablas, registros):
    return {
        'header': {
            'metric': tipo,
            'titulo': titulo,
            'rango': _texto_rango(filtros.get('desde'), filtros.get('hasta')),
            'sede': _etiqueta_sede_documento(user, filtros),
            'generado_por': obtener_nombre_autor(user.id),
            'generado_en': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'registros': registros,
        },
        'detalle_tablas': tablas,
    }


# =============================================================================
# 1) ACCESOS
# =============================================================================
def construir_accesos(user, filtros):
    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))
    is_admin = getattr(user, 'is_admin', False)
    is_finance = getattr(user, 'is_finance', False)

    es_global, sede_id, sede_nombre = _resolver_sede(filtros.get('sede'))

    query = LoginAudit.query.options(
        joinedload(LoginAudit.user),
        joinedload(LoginAudit.role),
        joinedload(LoginAudit.location)
    )

    if is_finance and not is_admin:
        loc_ids = [loc.id for loc in user.locations]
        query = query.filter(LoginAudit.location_id.in_(loc_ids))
        query = query.join(LoginAudit.role).filter(
            Role.name.notin_(['Administrator', 'Admin', 'Guest'])
        )
        if es_global:
            query = query.filter(LoginAudit.location_id.is_(None))
        elif sede_id:
            query = query.filter(LoginAudit.location_id == sede_id)
    else:
        if es_global:
            query = query.filter(LoginAudit.location_id.is_(None))
        elif sede_id:
            query = query.filter(LoginAudit.location_id == sede_id)
        elif sede_nombre:
            loc = _buscar_sede_por_nombre(sede_nombre)
            if not loc:
                return _base('accesos', 'Auditoría de Accesos', user, filtros,
                             [], 0)
            query = query.filter(LoginAudit.location_id == loc.id)

    if desde:
        query = query.filter(LoginAudit.timestamp >= desde)
    if hasta:
        query = query.filter(LoginAudit.timestamp <= hasta)

    logs = query.order_by(LoginAudit.timestamp.desc()).all()

    # Búsqueda y hora exacta como en pantalla (Auditoría de Accesos)
    q = (filtros.get('q') or '').lower().strip()
    hour = (filtros.get('hour') or '').strip().upper()
    if q or hour:
        def _coincide(log):
            if hour and (not log.timestamp
                         or log.timestamp.strftime('%I %p') != hour):
                return False
            if not q:
                return True
            texto = ' '.join(str(x) for x in (
                log.timestamp.strftime('%d/%m/%Y %I:%M %p')
                if log.timestamp else '',
                log.action,
                log.user.name if log.user else 'Sistema',
                log.user.email if log.user else '',
                log.role.name if log.role else '',
                log.location.name if log.location else 'Global / Sin Sede',
            ))
            return q in texto.lower()
        logs = [log for log in logs if _coincide(log)]

    items = []
    for log in logs:
        nombre = log.user.name if log.user else 'Sistema'
        correo = log.user.email if log.user else ''
        items.append({
            'banda': _etiqueta_accion(log.action),
            'derecha': _ts(log.timestamp),
            'filas': [
                ('Usuario',
                 f"{nombre} ({correo})" if correo else nombre),
                ('Rol', log.role.name if log.role else '—'),
                ('Sede', (log.location.name if log.location
                          else 'Global / Sin Sede')),
            ],
        })

    tablas = [{
        'tipo': 'accesos',
        'titulo': 'Eventos de acceso',
        'columnas': ['Fecha y hora', 'Acción', 'Usuario', 'Correo', 'Rol',
                     'Sede'],
        'filas': [[_ts(log.timestamp), _etiqueta_accion(log.action),
                   log.user.name if log.user else 'Sistema',
                   log.user.email if log.user else '',
                   log.role.name if log.role else '—',
                   log.location.name if log.location
                   else 'Global / Sin Sede']
                  for log in logs],
        'items': items,
    }]

    return _base('accesos', 'Auditoría de Accesos', user, filtros, tablas,
                 len(logs))


# =============================================================================
# 2) PERSONAL (USUARIOS)
# =============================================================================
def construir_usuarios(user, filtros):
    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))
    _, sede_id, _ = _resolver_sede(filtros.get('sede'))
    f = {}
    if getattr(user, 'is_admin', False) and sede_id:
        f['sede'] = sede_id
    if desde:
        f['desde'] = desde
    if hasta:
        f['hasta'] = hasta

    audits = AuditUserRepository.get_user_audits(current_user=user, filtros=f)

    # Búsqueda del apartado (genericSearchInput) igual que en pantalla
    q = (filtros.get('q') or '').lower().strip()
    if q:
        def _coincide(a):
            texto = ' '.join(str(x) for x in (
                _ts(a.timestamp),
                a.responsible_user.name if a.responsible_user else 'Sistema',
                a.role.name if a.role else '',
                a.action,
                a.target_user.name if a.target_user else '—',
                a.target_user.email if a.target_user else '',
                _detalles_cambiados(a.changed_data),
            ))
            return q in texto.lower()
        audits = [a for a in audits if _coincide(a)]

    items = []
    filas = []
    for audit in audits:
        cambios = _cambios_lista(audit.changed_data)
        responsable = (audit.responsible_user.name
                       if audit.responsible_user else 'Sistema')
        rol = audit.role.name if audit.role else ''
        target = (audit.target_user.name if audit.target_user else '—')
        correo = audit.target_user.email if audit.target_user else ''
        items.append({
            'banda': _etiqueta_accion(audit.action),
            'derecha': _ts(audit.timestamp),
            'filas': [
                ('Responsable',
                 f"{responsable} ({rol})" if rol else responsable),
                ('Usuario afectado',
                 f"{target} ({correo})" if correo and audit.target_user
                 else target),
                ('Cambios', '\n'.join(cambios) if cambios else '—'),
            ],
        })
        filas.append([
            _ts(audit.timestamp),
            audit.responsible_user.name if audit.responsible_user else 'Sistema',
            _etiqueta_accion(audit.action),
            audit.target_user.name if audit.target_user else '—',
            audit.target_user.email if audit.target_user else '',
            _detalles_cambiados(audit.changed_data),
        ])

    tablas = [{
        'tipo': 'personal',
        'titulo': 'Registro de auditoría de personal',
        'columnas': ['Fecha y hora', 'Responsable', 'Acción',
                     'Usuario afectado', 'Correo', 'Detalles'],
        'filas': filas,
        'items': items,
    }]

    return _base('personal', 'Auditoría de Personal', user, filtros, tablas,
                 len(audits))


# =============================================================================
# 3) COMPRAS
# =============================================================================
def construir_compras(user, filtros):
    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))
    _, sede_id, _ = _resolver_sede(filtros.get('sede'))
    f = {}
    if getattr(user, 'is_admin', False) and sede_id:
        f['sede'] = sede_id
    if desde:
        f['desde'] = desde
    if hasta:
        f['hasta'] = hasta

    audits = AuditPurchaseService.list_purchase_audits(user, filtros=f)

    # Búsqueda del apartado (genericSearchInput) igual que en pantalla
    q = (filtros.get('q') or '').lower().strip()
    if q:
        def _coincide(a):
            texto = ' '.join(str(x) for x in (
                _ts(a['timestamp']),
                a['user_name'], a['role_name'], a['action_type'],
                f"Factura #{a['purchase_id']}" if a.get('purchase_id') else '',
                _detalles_cambiados(a['changed_data']),
            ))
            return q in texto.lower()
        audits = [a for a in audits if _coincide(a)]

    items = []
    for audit in audits:
        cambios = _cambios_lista(audit['changed_data'])
        items.append({
            'banda': _etiqueta_accion(audit['action_type']),
            'derecha': _ts(audit['timestamp']),
            'filas': [
                ('Responsable',
                 f"{audit['user_name']} ({audit['role_name']})"
                 if audit.get('role_name') else audit['user_name']),
                ('Compra', f"Factura #{audit['purchase_id']}"
                 if audit.get('purchase_id') else '—'),
                ('Cambios', '\n'.join(cambios) if cambios else '—'),
            ],
        })

    tablas = [{
        'tipo': 'compras',
        'titulo': 'Registro de auditoría de compras',
        'columnas': ['Fecha y hora', 'Responsable', 'Rol', 'Acción', 'Compra',
                     'Detalles'],
        'filas': [[_ts(audit['timestamp']), audit['user_name'],
                   audit['role_name'],
                   _etiqueta_accion(audit['action_type']),
                   f"Factura #{audit['purchase_id']}"
                   if audit.get('purchase_id') else '—',
                   _detalles_cambiados(audit['changed_data'])]
                  for audit in audits],
        'items': items,
    }]

    return _base('compras', 'Auditoría de Compras', user, filtros, tablas,
                 len(audits))


def construir_listado_compras(user, filtros):
    """Exporta el listado de Gestión de Compras con los filtros de pantalla.

    Replica el filtrado client-side (búsqueda #id/proveedor, proveedor exacto,
    fecha exacta) para que lo descargado coincida con lo visible.
    """
    from app.logistics.repositories.purchase_management_repository import (
        PurchaseManagementRepository,
    )
    from app.logistics.services.purchase_management_service import (
        PurchaseManagementService,
    )

    service = PurchaseManagementService(PurchaseManagementRepository(db))
    purchases = service.get_formatted_history(current_user=user)

    q = (filtros.get('q') or '').replace('#', '').strip().lower()
    supplier = (filtros.get('supplier') or '').strip().lower()
    fecha = (filtros.get('date') or '').strip()

    filtradas = []
    for p in purchases:
        if q and q not in str(p['id']).lower() and q not in p['supplier_name'].lower():
            continue
        if supplier and p['supplier_name'].lower() != supplier:
            continue
        if fecha:
            pd = p['purchase_date']
            if not pd or pd.strftime('%Y-%m-%d') != fecha:
                continue
        filtradas.append(p)

    if fecha:
        filtros['desde'] = datetime.strptime(fecha, '%Y-%m-%d').date()
        filtros['hasta'] = datetime.strptime(fecha, '%Y-%m-%d').date()

    items = []
    for p in filtradas:
        estado = ('COMPLETADA' if p['status'] == 'COMPLETED'
                  else 'ANULADA')
        fecha = (p['purchase_date'].strftime('%d/%m/%Y %I:%M %p')
                 if p['purchase_date'] else '—')
        items.append({
            'banda': f"Compra #{p['id']}",
            'derecha': estado,
            'filas': [
                ('Proveedor', p['supplier_name']),
                ('Fecha de Compra', fecha),
                ('Monto Total', f"{p['total_amount']} {p['currency']}"),
                ('Total en Bs.', f"Bs. {p['total_bs']}"),
                ('Moneda', p['currency']),
                ('Tasa Aplicada', f"Bs. {p['exchange_rate']}"),
                ('Estado', estado),
            ],
        })

    tablas = [{
        'tipo': 'compras-listado',
        'titulo': 'Listado de compras registradas',
        'columnas': ['Identificación', 'Proveedor', 'Fecha de Compra',
                     'Monto Total', 'Total en Bs.', 'Moneda', 'Tasa Aplicada',
                     'Estado'],
        'filas': [[f"#{p['id']}", p['supplier_name'],
                   p['purchase_date'].strftime('%d/%m/%Y %I:%M %p')
                   if p['purchase_date'] else '—',
                   f"{p['total_amount']} {p['currency']}",
                   f"Bs. {p['total_bs']}",
                   p['currency'],
                   f"Bs. {p['exchange_rate']}",
                   'COMPLETED' if p['status'] == 'COMPLETED' else 'ANULADA']
                  for p in filtradas],
        'items': items,
    }]

    return _base('compras-listado', 'Gestión de Compras', user, filtros,
                 tablas, len(filtradas))


def construir_detalle_compra(user, purchase_id, filtros):
    """Prepara el documento exportable de una compra individual.

    Incluye los datos maestros de la transacción, la tabla de insumos
    adquiridos y, si existen, las modificaciones posteriores registradas.
    """
    from app.models.inventory_model import Product
    from app.models.logistics_model import (Purchase, PurchaseAuditLog,
                                             PurchaseDetail, Supplier)
    from app.models.security_model import User

    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return {'error': 'La compra solicitada no existe.'}

    supplier = (db.session.get(Supplier, purchase.supplier_id)
                if purchase.supplier_id else None)
    creator = (db.session.get(User, purchase.user_id) if purchase.user_id
               else None)

    filas = (db.session.query(PurchaseDetail, Product.name, Product.sku)
             .join(Product, PurchaseDetail.product_id == Product.id)
             .filter(PurchaseDetail.purchase_id == purchase_id).all())

    edit_logs = (PurchaseAuditLog.query
                 .filter_by(purchase_id=purchase_id, action_type='EDIT')
                 .order_by(PurchaseAuditLog.timestamp.asc()).all())

    fecha_local = (purchase.purchase_date - timedelta(hours=4)
                   if purchase.purchase_date else None)
    tasa = purchase.exchange_rate or 0

    insumos = []
    total_bs = 0
    for fila in filas:
        item, nombre_raw, sku = fila
        nombre = nombre_raw or f'Insumo #{item.product_id}'
        precio_bs = (float(item.quantity) * float(item.foreign_price)
                     * float(tasa))
        total_bs += precio_bs
        insumos.append([
            f"{nombre} ({sku})" if sku else nombre,
            f"{item.quantity}",
            item.lot_number or 'N/A',
            item.expiration_date.strftime('%d/%m/%Y')
            if item.expiration_date else 'N/A',
            f"{item.foreign_price} {purchase.currency}",
            f"Bs. {precio_bs:,.2f}",
        ])

    tablas = [{
        'tipo': 'transaccion',
        'titulo': 'Datos de la Transacción',
        'columnas': ['Concepto', 'Valor'],
        'filas': [
            ['N° de Compra', f"#{purchase.id}"],
            ['Proveedor', supplier.name if supplier else 'N/A'],
            ['RIF', supplier.tax_id if supplier else 'N/A'],
            ['Registrado por', creator.name if creator else 'Sistema'],
            ['Fecha de Compra',
             fecha_local.strftime('%d/%m/%Y %I:%M %p') if fecha_local else '—'],
            ['Moneda', purchase.currency or '—'],
            ['Tasa Aplicada', f"1 {purchase.currency} = {tasa} Bs."],
            ['Monto Total Facturado',
             f"{purchase.total_amount} {purchase.currency}"],
            ['Total en Bs.', f"Bs. {total_bs:,.2f}"],
            ['Estado', 'ANULADA' if purchase.status == 'ANNULLED'
             else 'COMPLETADA'],
        ],
        'items': [{
            'banda': f"Compra #{purchase.id}",
            'derecha': ('ANULADA' if purchase.status == 'ANNULLED'
                        else 'COMPLETADA'),
            'filas': [
                ('Proveedor', supplier.name if supplier else 'N/A'),
                ('RIF', supplier.tax_id if supplier else 'N/A'),
                ('Registrado por', creator.name if creator else 'Sistema'),
                ('Fecha de Compra',
                 fecha_local.strftime('%d/%m/%Y %I:%M %p')
                 if fecha_local else '—'),
                ('Moneda', purchase.currency or '—'),
                ('Tasa Aplicada', f"1 {purchase.currency} = {tasa} Bs."),
                ('Monto Total Facturado',
                 f"{purchase.total_amount} {purchase.currency}"),
                ('Total en Bs.', f"Bs. {total_bs:,.2f}"),
                ('Estado', 'ANULADA' if purchase.status == 'ANNULLED'
                 else 'COMPLETADA'),
            ],
        }],
    }]
    if insumos:
        tablas.append((
            'Insumos Adquiridos',
            ['Insumo', 'Cant.', 'N° Lote', 'Vencimiento',
             'Precio Unit.', 'Total en Bs.'],
            insumos,
        ))

    if edit_logs:
        modificaciones = []
        for log in edit_logs:
            editor = (db.session.get(User, log.user_id) if log.user_id
                      else None)
            fecha = (log.timestamp - timedelta(hours=4)
                     if log.timestamp else None)
            motivo = ((log.new_data or {}).get('edit_reason')
                      or 'Edición sin motivo especificado')
            cambios = _cambios_edicion_compra(log)
            if cambios:
                for cambio in cambios:
                    modificaciones.append([
                        fecha.strftime('%d/%m/%Y %I:%M %p') if fecha else '—',
                        editor.name if editor else 'Usuario Desconocido',
                        motivo,
                        cambio['field'],
                        str(cambio['from']) if cambio['from'] != '-'
                        else '-',
                        str(cambio['to']),
                    ])
            else:
                modificaciones.append([
                    fecha.strftime('%d/%m/%Y %I:%M %p') if fecha else '—',
                    editor.name if editor else 'Usuario Desconocido',
                    motivo,
                    '—',
                    '—',
                    'Sin cambios de cantidades, fechas o precios.',
                ])
        tablas.append((
            'Historial de Modificaciones',
            ['Fecha y Hora', 'Editor', 'Motivo', 'Campo Modificado',
             'Antes', 'Después'],
            modificaciones,
        ))

    documento = _base(f'compra-detalle', f'Detalle de Compra #{purchase.id}',
                      user, filtros, tablas, len(insumos))
    documento['header']['rango'] = (
        f"Fecha de compra: {fecha_local.strftime('%d/%m/%Y %I:%M %p')}"
        if fecha_local else 'Fecha de compra: —')
    documento['header']['sede'] = (
        f"Proveedor: {supplier.name}" if supplier else 'Proveedor: N/A')
    return documento


def _cambios_edicion_compra(log):
    """Replica las diferencias visualizadas en el detalle de la compra."""
    from app.models.inventory_model import Product

    cambios = []
    prev = log.previous_data or {}
    curr = log.new_data or {}

    if prev.get('total_amount') != curr.get('total_amount'):
        cambios.append({'field': 'Costo Total de la Factura',
                        'from': prev.get('total_amount'),
                        'to': curr.get('total_amount')})
    if prev.get('exchange_rate') != curr.get('exchange_rate'):
        cambios.append({'field': 'Tasa de Cambio Aplicada',
                        'from': prev.get('exchange_rate'),
                        'to': curr.get('exchange_rate')})

    prev_details = {str(d.get('id', d.get('product_id'))): d
                    for d in prev.get('details', [])}
    curr_details = {str(d.get('id', d.get('product_id'))): d
                    for d in curr.get('details', [])}

    for key in set(list(prev_details.keys()) + list(curr_details.keys())):
        p_item = prev_details.get(key)
        c_item = curr_details.get(key)
        prod_id = (p_item['product_id'] if p_item else c_item['product_id'])
        product_obj = Product.query.get(prod_id)
        prod_name = product_obj.name if product_obj else f"Insumo ID {prod_id}"

        if not p_item and c_item:
            cambios.append({'field': f'Insumo Añadido: {prod_name}', 'from': '-',
                            'to': (f"Cant. Comprada: {c_item.get('quantity')} | "
                                   f"Lote: {c_item.get('lot_number')} | "
                                   f"Precio Unitario: {c_item.get('foreign_price')}")})
        elif p_item and not c_item:
            cambios.append({'field': f'Insumo Eliminado: {prod_name}',
                            'from': (f"Cant. Comprada: {p_item.get('quantity')} | "
                                     f"Lote: {p_item.get('lot_number')} | "
                                     f"Precio Unitario: {p_item.get('foreign_price')}"),
                            'to': '-'})
        else:
            if str(float(p_item.get('quantity', 0))) != str(float(c_item.get('quantity', 0))):
                cambios.append({'field': f'Cantidad Comprada de {prod_name}',
                                'from': p_item.get('quantity'),
                                'to': c_item.get('quantity')})
            if str(float(p_item.get('foreign_price', 0))) != str(float(c_item.get('foreign_price', 0))):
                cambios.append({'field': f'Precio Unitario de {prod_name} (Cant. Comprada: {c_item.get("quantity")})',
                                'from': p_item.get('foreign_price'),
                                'to': c_item.get('foreign_price')})
            p_date = str(p_item.get('expiration_date')) if p_item.get('expiration_date') else 'N/A'
            c_date = str(c_item.get('expiration_date')) if c_item.get('expiration_date') else 'N/A'
            if p_date != c_date:
                cambios.append({'field': f'Fecha de Vencimiento de {prod_name}',
                                'from': p_date, 'to': c_date})
            p_lot = str(p_item.get('lot_number')) if p_item.get('lot_number') else 'N/A'
            c_lot = str(c_item.get('lot_number')) if c_item.get('lot_number') else 'N/A'
            if p_lot != c_lot:
                cambios.append({'field': f'Número de Lote de {prod_name}',
                                'from': p_lot, 'to': c_lot})
    return cambios


# =============================================================================
# 4) TRASLADOS (MOVIMIENTOS)
# =============================================================================
def construir_movimientos(user, filtros):
    from app.logistics.services.movement_audit_service import MovementAuditService

    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))
    _, sede_id, sede_nombre = _resolver_sede(filtros.get('sede'))
    f = {}
    if getattr(user, 'is_finance', False) and not getattr(user, 'is_admin', False):
        f['allowed_locations'] = [loc.id for loc in user.locations]
    elif getattr(user, 'is_admin', False) and sede_id:
        f['location_id'] = sede_id
    if filtros.get('severity'):
        f['severity'] = filtros['severity']
    if desde:
        f['start_date'] = desde
    if hasta:
        f['end_date'] = hasta

    movements, bajas = MovementAuditService.get_structured_audits(f)

    q = (filtros.get('q') or '').lower().strip()
    if q:
        def _coincide(m):
            texto = ' '.join(str(x) for x in (
                m.get('movement_id'), m.get('origin_name'), m.get('destination_name'),
                m.get('status')
            ))
            for evt in m.get('events', []):
                texto += ' ' + str(getattr(evt, 'action', ''))
                if getattr(evt, 'user', None) and getattr(evt.user, 'name', None):
                    texto += ' ' + evt.user.name
                if getattr(evt, 'location', None) and getattr(evt.location, 'name', None):
                    texto += ' ' + evt.location.name
            return q in texto.lower()
        movements = [m for m in movements if _coincide(m)]

        def _coincide_baja(b):
            texto = ' '.join(str(x) for x in (
                b.get('movement_id'), b.get('location_name'), b.get('user_name'),
                b.get('dispatcher_name'), b.get('reason')
            ))
            return q in texto.lower()
        bajas = [b for b in bajas if _coincide_baja(b)]

    items_actividad = [{
        'banda': f"Traslado {m['movement_id']}",
        'derecha': _ts(m['last_event']),
        'filas': [
            ('Ruta',
             f"{m.get('origin_name', '')} → {m.get('destination_name', '')}"),
            ('Estado', m.get('status') or 'Registro histórico'),
            ('Eventos', f"{len(m['events'])}"),
            ('Último evento', _ts(m['last_event'])),
        ],
    } for m in movements]

    items_eventos = []
    for m in movements:
        for evt in m['events']:
            items_eventos.append({
                'banda': _etiqueta_evento(evt),
                'derecha': _ts(evt.timestamp),
                'filas': [
                    ('Traslado', m['movement_id']),
                    ('Responsable', evt.user.name if evt.user else 'Sistema'),
                    ('Sede', evt.location.name if evt.location else 'General'),
                    ('Severidad', getattr(evt, 'severity', None) or 'NORMAL'),
                    ('Detalle', _detalle_evento_traslado(evt)),
                ],
            })

    items_bajas = [{
        'banda': 'Cancelación de envío',
        'derecha': _ts(b['timestamp']),
        'filas': [
            ('Traslado', b['movement_id']),
            ('Sede', b['location_name']),
            ('Canceló', b['user_name']),
            ('Enviado por', b['dispatcher_name']),
            ('Motivo', b['reason']),
            ('Ítems devueltos', f"{len(b['items'] or [])} · {b['total_reverted']}"),
        ],
    } for b in bajas]

    items_devueltos = []
    for b in bajas:
        for item in (b['items'] or []):
            items_devueltos.append([
                _ts(b['timestamp']), b['movement_id'],
                item.get('sku', 'N/A'), item.get('product_name', 'N/A'),
                item.get('lot_number', 'N/A'),
                item.get('expiration_date', 'N/A'),
                _fmt_qty(item.get('dispatched_qty', 0)),
            ])

    tablas = [
        {
            'tipo': 'movimientos',
            'titulo': 'Actividad por traslado',
            'columnas': ['Traslado', 'Ruta', 'Estado', 'Eventos',
                         'Último evento'],
            'filas': [[m['movement_id'],
                       f"{m.get('origin_name', '')} → {m.get('destination_name', '')}",
                       m.get('status') or 'Registro histórico', len(m['events']),
                       _ts(m['last_event'])]
                      for m in movements],
            'items': items_actividad,
        },
        {
            'tipo': 'movimientos',
            'titulo': 'Detalle de eventos',
            'columnas': ['Fecha y hora', 'Traslado', 'Acción', 'Responsable',
                         'Sede', 'Severidad',
                         'Detalle completo de la auditoría'],
            'filas': [[_ts(evt.timestamp), m['movement_id'],
                       _etiqueta_evento(evt),
                       evt.user.name if evt.user else 'Sistema',
                       evt.location.name if evt.location else 'General',
                       getattr(evt, 'severity', None) or 'NORMAL',
                       _detalle_evento_traslado(evt)]
                      for m in movements for evt in m['events']],
            'items': items_eventos,
        },
        {
            'tipo': 'movimientos',
            'titulo': 'Cancelación de envíos',
            'columnas': ['Fecha', 'Traslado', 'Sede', 'Canceló',
                         'Enviado por', 'Motivo', 'Ítems devueltos'],
            'filas': [[_ts(b['timestamp']), b['movement_id'],
                       b['location_name'], b['user_name'],
                       b['dispatcher_name'], b['reason'],
                       f"{len(b['items'] or [])} · {b['total_reverted']}"]
                      for b in bajas],
            'items': items_bajas,
        },
        ]

    items_devueltos = []
    for b in bajas:
        for item in (b['items'] or []):
            items_devueltos.append([
                _ts(b['timestamp']), b['movement_id'],
                item.get('sku', 'N/A'), item.get('product_name', 'N/A'),
                item.get('lot_number', 'N/A'),
                item.get('expiration_date', 'N/A'),
                _fmt_qty(item.get('dispatched_qty', 0)),
            ])
    tablas.append((
        'Mercancía devuelta (cancelación de envíos)',
        ['Fecha', 'Traslado', 'SKU', 'Producto', 'Lote', 'Vencimiento',
         'Cant. devuelta'],
        items_devueltos,
    ))

    registros = (len(movements)
                 + sum(len(m['events']) for m in movements) + len(bajas))

    return _base('movimientos', 'Auditoría de Traslados', user, filtros, tablas,
                 registros)


# =============================================================================
# 5) MERMAS
# =============================================================================
def construir_mermas(user, filtros):
    from app.waste.services.waste_audit_service import WasteAuditService

    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))
    es_global, sede_id, sede_nombre = _resolver_sede(filtros.get('sede'))

    location_override = None
    sede_nombre_pendiente = None
    if getattr(user, 'is_finance', False) and not getattr(user, 'is_admin', False):
        location_override = [loc.id for loc in user.locations]
    elif getattr(user, 'is_admin', False) and (sede_id or sede_nombre):
        if sede_id:
            location_override = [sede_id]
        else:
            loc = _buscar_sede_por_nombre(sede_nombre)
            if loc:
                location_override = [loc.id]
            else:
                sede_nombre_pendiente = sede_nombre

    f = {}
    if desde:
        f['start_date'] = desde
    if hasta:
        f['end_date'] = hasta
    if filtros.get('severity'):
        f['severity'] = filtros['severity']

    trail = WasteAuditService.get_formatted_audit_trail(
        user, f, location_ids_override=location_override)

    # Refiltro exacto a pantalla: sede por nombre (si no se resolvió a id),
    # severidad y texto de búsqueda (producto/sede/responsable).
    q = (filtros.get('q') or '').lower().strip()
    sev = (filtros.get('severity') or '').upper() or None
    if sede_nombre_pendiente or sev or q:
        def _coincide(item):
            loc_disp = (item.get('location') or '').lower()
            if sede_nombre_pendiente and loc_disp != sede_nombre_pendiente:
                return False
            if sev and (item.get('severity') or '').upper() != sev:
                return False
            if not q:
                return True
            data = item.get('changed_data') or {}
            productos = ' '.join(
                f"{p.get('producto', '')} {p.get('lote', '')}"
                for p in (data.get('productos') or [])
            )
            texto = ' '.join(str(x) for x in (
                item.get('user', ''), loc_disp, productos.lower(),
            ))
            return q in texto.lower()
        trail = [t for t in trail if _coincide(t)]

    filas = []
    items = []
    for item in trail:
        data = item.get('changed_data') or {}
        filas.append([
            item.get('timestamp'), item.get('user'), item.get('location'),
            item.get('status'), item.get('severity'),
            _tipos_merma(data),
            _productos_merma(data),
            _detalle_merma(item),
        ])
        items.append({
            'banda': item.get('status') or 'Merma',
            'derecha': item.get('timestamp'),
            'filas': [
                ('Responsable', item.get('user') or '—'),
                ('Sede', item.get('location') or '—'),
                ('Gravedad', item.get('severity') or '—'),
                ('Tipo(s) de merma', _tipos_merma(data)),
                ('Producto(s)', _productos_merma(data)),
                ('Detalle completo', _detalle_merma(item)),
            ],
        })
    tablas = [{
        'tipo': 'mermas',
        'titulo': 'Eventos de mermas',
        'columnas': ['Fecha y hora', 'Responsable', 'Sede', 'Estado',
                     'Gravedad', 'Tipo(s) de merma', 'Producto(s)',
                     'Detalle completo de la merma'],
        'filas': filas,
        'items': items,
    }]

    productos_filas = []
    for item in trail:
        data = item.get('changed_data') or {}
        for p in data.get('productos') or []:
            unidad = _unidad_merma(p)
            tipo = p.get('motivo_tipo') or p.get('motivo_after') \
                or 'No especificado'
            cambio = ''
            if p.get('cambio_cantidad'):
                cambio = (f"{_fmt_qty(p.get('cantidad_antes') or 0)} → "
                          f"{_fmt_qty(p.get('cantidad') or 0)}")
            productos_filas.append([
                item.get('timestamp'), item.get('user'),
                item.get('location'), item.get('status'),
                p.get('producto') or '—', p.get('lote') or 'N/A',
                f"{_fmt_qty(p.get('cantidad') or 0)} {unidad}".strip(),
                cambio or '—',
                tipo,
                p.get('motivo') or '—',
                p.get('decision') or '—',
            ])
    # Solo Excel: el detalle por producto ya está en las tarjetas del PDF.
    tablas.append({
        'tipo': 'mermas-productos',
        'titulo': 'Productos mermados',
        'solo_excel': True,
        'columnas': ['Fecha y hora', 'Responsable', 'Sede', 'Estado',
                     'Producto', 'Lote', 'Cantidad', 'Cambio de cantidad',
                     'Tipo de merma', 'Motivo', 'Decisión'],
        'filas': productos_filas,
    })

    return _base('mermas', 'Auditoría de Mermas', user, filtros, tablas,
                 len(trail))


def _unidad_merma(p):
    """Unidad de medida legible del producto mermado."""
    return {'UN': 'und', 'KG': 'kg'}.get(
        (p.get('unidad') or '').upper(), p.get('unidad') or 'und/kg')


def _tipos_merma(data):
    """Todos los tipos de merma de la merma (uno por producto si difieren)."""
    tipos = []
    for p in data.get('productos') or []:
        t = (p.get('motivo_tipo') or p.get('motivo_after') or '').strip()
        if t and t not in tipos:
            tipos.append(t)
    if not tipos:
        base = (data.get('tipo_merma') or '').strip()
        tipos = [base] if base else ['No especificado']
    return ' · '.join(tipos)


def _productos_merma(data):
    """Resumen de productos mermados (producto + cantidad + unidad)."""
    partes = []
    for p in data.get('productos') or []:
        partes.append(
            f"{p.get('producto', '')}"
            f" {_fmt_qty(p.get('cantidad') or 0)} {_unidad_merma(p)}".strip())
    return ' · '.join(partes) or '—'


def _detalle_merma(item):
    """Texto completo de una merma (productos, cantidades y motivos)."""
    data = item.get('changed_data') or {}
    lineas = [f"TIPO(S) DE MERMA: {_tipos_merma(data)}"]
    lineas.append(
        f"ESTADO: {item.get('status') or 'N/A'} | "
        f"GRAVEDAD: {item.get('severity') or 'N/A'}")

    productos = data.get('productos') or []
    if productos:
        lineas.append(f'PRODUCTOS MERMADOS ({len(productos)}):')
        for p in productos:
            unidad = _unidad_merma(p)
            cab = f"  · {p.get('producto') or 'Producto'}"
            if p.get('lote'):
                cab += f" | Lote: {p['lote']}"
            if p.get('cantidad_antes') is not None:
                cab += (f" | Cant: {_fmt_qty(p.get('cantidad_antes'))} → "
                        f"{_fmt_qty(p.get('cantidad'))} {unidad}")
            else:
                cab += f" | Cant: {_fmt_qty(p.get('cantidad') or 0)} {unidad}"
            tipo = p.get('motivo_tipo') or p.get('motivo_after')
            if p.get('motivo_tipo_antes') and tipo:
                cab += f" | Motivo: {p['motivo_tipo_antes']} → {tipo}"
            elif tipo:
                cab += f" | Motivo tipo: {tipo}"
            if p.get('motivo'):
                cab += f" | Detalle: {p['motivo']}"
            if p.get('decision'):
                cab += f" | Decisión: {p['decision']}"
            lineas.append(cab)
    else:
        lineas.append('PRODUCTOS MERMADOS: Sin desglose.')

    for etiqueta, clave in (
        ('MOTIVO DE REGISTRO', 'motivo_registro'),
        ('MOTIVO DE EDICIÓN', 'motivo_edicion'),
        ('MOTIVO DE RECHAZO', 'motivo_rechazo'),
        ('MOTIVO DE REVERSIÓN', 'motivo_reversion'),
    ):
        if data.get(clave):
            lineas.append(f"{etiqueta}: {data[clave]}")
    if data.get('decididas') is not None and data.get('rechazadas') is not None:
        lineas.append(f"DECISIONES: {data['decididas']} aprobado(s) / "
                      f"{data['rechazadas']} rechazado(s)")
    if data.get('impacto_stock'):
        lineas.append(f"IMPACTO EN INVENTARIO: {data['impacto_stock']}")
    return '\n'.join(lineas)


def _lado_inventario(e):
    """Mismo criterio que pantalla (auditinventory_routes): qty positivo →
    ingresos, negativo → egresos; con qty neutro decide por acción (MERMA en
    espera, cancelaciones, pendientes... → egresos)."""
    qty = e.get('qty', 0)
    if qty > 0:
        return 'ingreso'
    if qty < 0:
        return 'egreso'
    act = (e.get('action') or '').upper()
    if any(kw in act for kw in ('INGRESO', 'COMPRA', 'RECEPCION', 'REABASTEC',
                                'ACTIVACION', 'DEVOLUCION', 'ACREDITACION')):
        return 'ingreso'
    return 'egreso'


def _fila_inventario(r):
    return [
        r.get('id'), _ts(r.get('ts')), r.get('sede'),
        r.get('action'), r.get('sev_label'), r.get('user_name'),
        r.get('product'), r.get('qty'), (r.get('notes') or '')[:200],
    ]


def _item_inventario_tarjeta(r, lado):
    """Tarjeta de una entrada de inventario (ingreso o egreso)."""
    return {
        'banda': lado,
        'derecha': _ts(r.get('ts')),
        'filas': [
            ('ID', r.get('id')),
            ('Sede', r.get('sede')),
            ('Acción', r.get('action')),
            ('Estado', r.get('sev_label')),
            ('Responsable', r.get('user_name')),
            ('Insumo', r.get('product')),
            ('Cantidad', r.get('qty')),
            ('Notas', (r.get('notes') or '').strip() or '—'),
        ],
    }


# =============================================================================
# 6) INVENTARIO
# =============================================================================
def construir_inventario(user, filtros):
    from app.waste.services.auditinventory_service import get_inventory_audit_entries

    role_id = getattr(user, 'role_id', None)
    is_admin = (role_id == 1)
    desde, hasta = _rango_datetimes(filtros.get('desde'), filtros.get('hasta'))

    f = {'severity': filtros.get('severity'), 'tab': filtros.get('tab')}
    if is_admin:
        f['location_id'] = filtros.get('sede')
    else:
        f['location_id'] = getattr(user, 'location_id', None)
    f['start_date'] = desde
    f['end_date'] = hasta

    rows = get_inventory_audit_entries(f, user, is_admin)

    # Búsqueda de la pantalla de inventario (auditSearchInput sobre data-search)
    q = (filtros.get('q') or '').lower().strip()
    if q:
        def _coincide(r):
            texto = ' '.join(str(x) for x in (
                'Ingreso' if _lado_inventario(r) == 'ingreso' else 'Egreso',
                r.get('product'), r.get('sede'), r.get('user_name'),
                r.get('action'), r.get('movement_id') or '',
            ))
            return q in texto.lower()
        rows = [r for r in rows if _coincide(r)]

    ingresos = [r for r in rows if _lado_inventario(r) == 'ingreso']
    egresos = [r for r in rows if _lado_inventario(r) == 'egreso']

    # Ambas secciones siempre presentes (como en pantalla): si una no trae
    # filas, el generador muestra "Sin registros" en su tabla.
    COLUMNAS_INVENTARIO = ['ID', 'Fecha y hora', 'Sede', 'Acción', 'Estado',
                           'Responsable', 'Insumo', 'Cantidad', 'Notas']
    tablas = [
        {'tipo': 'inventario', 'titulo': 'Ingresos de inventario',
         'columnas': COLUMNAS_INVENTARIO,
         'filas': [_fila_inventario(r) for r in ingresos],
         'items': [_item_inventario_tarjeta(r, 'Ingreso') for r in ingresos]},
        {'tipo': 'inventario', 'titulo': 'Egresos de inventario',
         'columnas': COLUMNAS_INVENTARIO,
         'filas': [_fila_inventario(r) for r in egresos],
         'items': [_item_inventario_tarjeta(r, 'Egreso') for r in egresos]},
    ]

    return _base('inventario', 'Auditoría de Inventario', user, filtros, tablas,
                 len(ingresos) + len(egresos))


_CONSTRUCTORES = {
    'accesos': construir_accesos,
    'usuarios': construir_usuarios,
    'compras': construir_compras,
    'movimientos': construir_movimientos,
    'mermas': construir_mermas,
    'inventario': construir_inventario,
}


def construir_documento(tipo, user, filtros):
    constructor = _CONSTRUCTORES.get(tipo)
    if not constructor:
        return {'error': 'Tipo de auditoría no soportado.'}
    return constructor(user, filtros)