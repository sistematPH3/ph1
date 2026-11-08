import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.security_model import User
from app.models.statistics_model import StatisticsSnapshot
from app.models.logistics_model import (ExchangeRateHistory, Location, Purchase,
                                         PurchaseDetail, Movement, MovementDetail)
from app.models.inventory_model import Product
from app.models.waste_model import AuditLog, Waste, WasteType


def obtener_sedes_permitidas(user_id):
    """Ids de sedes que el usuario puede ver. El admin ve todas las activas;
    el resto solo las que tiene asignadas en user_locations."""
    user = db.session.get(User, user_id)
    if user is None:
        return []
    if user.is_admin:
        return [loc.id for loc in Location.query.filter_by(is_active=True).all()]
    return [loc.id for loc in user.locations if loc.is_active]


def obtener_sedes_opciones(user_id):
    """Opciones (id, name) para el selector de sede de la pantalla."""
    ids = obtener_sedes_permitidas(user_id)
    if not ids:
        return []
    filas = db.session.query(Location.id, Location.name).filter(
        Location.id.in_(ids)).order_by(Location.name).all()
    return [{'id': rid, 'name': nombre} for rid, nombre in filas]


def obtener_snapshot(location_id, metric, period_type, period_start):
    """Un resumen exacto del cajón (idempotente por (sede, métrica, tipo, inicio))."""
    return StatisticsSnapshot.query.filter_by(
        location_id=location_id,
        metric=metric,
        period_type=period_type,
        period_start=period_start,
    ).first()


def obtener_snapshot_por_periodo(location_id, metric, period_type, period_start, period_end):
    """Suma de los resúmenes que caen dentro del rango [inicio, fin]."""
    row = db.session.query(
        func.coalesce(func.sum(StatisticsSnapshot.amount_usd), 0),
        func.coalesce(func.sum(StatisticsSnapshot.amount_bs), 0),
        func.coalesce(func.sum(StatisticsSnapshot.amount_eur), 0),
        func.coalesce(func.sum(StatisticsSnapshot.quantity), 0),
        func.coalesce(func.sum(StatisticsSnapshot.record_count), 0),
    ).filter(
        StatisticsSnapshot.location_id == location_id,
        StatisticsSnapshot.metric == metric,
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start >= period_start,
        StatisticsSnapshot.period_start <= period_end,
    ).first()

    return {
        'amount_usd': Decimal(str(row[0])),
        'amount_bs': Decimal(str(row[1])),
        'amount_eur': Decimal(str(row[2])),
        'quantity': Decimal(str(row[3])),
        'record_count': int(row[4] or 0),
    }


def _inicio_periodo(fecha, period_type):
    """Inicio del período (semana empieza en lunes) que contiene a 'fecha'."""
    ptype = (period_type or 'MONTHLY').upper()
    if ptype == 'WEEKLY':
        return fecha - timedelta(days=fecha.weekday())
    if ptype == 'QUARTERLY':
        trimestre = (fecha.month - 1) // 3
        return fecha.replace(year=fecha.year, month=trimestre * 3 + 1, day=1)
    if ptype == 'ANNUAL':
        return fecha.replace(month=1, day=1)
    return fecha.replace(day=1)


def listar_periodos_disponibles(location_ids, metric, period_type, limite=24):
    """Inicios de período disponibles para los selectores y el ancla. Primero
    los que ya estén en el cajón (statistics_snapshots); si el cajón no tiene
    nada para esta métrica (en la práctica nadie lo llena) se derivan de las
    fechas con registros REALES, de más reciente a más antigua."""
    if not location_ids:
        return []
    rows = db.session.query(StatisticsSnapshot.period_start).filter(
        StatisticsSnapshot.location_id.in_(location_ids),
        StatisticsSnapshot.metric == metric,
        StatisticsSnapshot.period_type == period_type,
    ).distinct().order_by(StatisticsSnapshot.period_start.desc()).limit(limite).all()
    if rows:
        return [row[0] for row in rows]

    # Cajón vacío: períodos de las fechas con datos reales.
    inicios = {_inicio_periodo(f, period_type)
               for f in fechas_con_registros(location_ids, metric)}
    return sorted(inicios, reverse=True)[:max(1, limite)]


def _totales_vacios():
    return {
        'amount_usd': Decimal('0.00'),
        'amount_bs': Decimal('0.00'),
        'amount_eur': Decimal('0.00'),
        'quantity': Decimal('0.00'),
        'record_count': 0,
    }


def obtener_totales_reales(location_ids, metric, desde, hasta):
    """Totales REALES del rango desde las tablas de origen, con el mismo
    contrato que un snapshot del cajón. Las compras pertenecen a la Central;
    el consumo de cocina, las mermas aprobadas y los traslados a las sedes
    dadas."""
    if not location_ids:
        return _totales_vacios()
    metric = (metric or 'PURCHASES').upper()
    totales = _totales_vacios()
    desde = desde if hasattr(desde, 'date') else desde
    hasta = hasta if hasattr(hasta, 'date') else hasta

    if metric in ('PURCHASES', 'CONSOLIDATED'):
        for fila in obtener_compras_por_moneda(desde, hasta):
            totales['amount_usd'] += fila['total_usd']
            totales['amount_bs'] += fila['total_bs']
            totales['amount_eur'] += fila['total_eur']
            totales['record_count'] += 1

    if metric in ('WASTE', 'CONSOLIDATED'):
        resumen = obtener_mermas_resumen(location_ids, desde, hasta)['total']
        totales['amount_usd'] += resumen.get('USD', Decimal('0.00'))
        totales['amount_bs'] += resumen.get('BS', Decimal('0.00'))
        totales['amount_eur'] += resumen.get('EUR', Decimal('0.00'))
        totales['record_count'] += int(db.session.query(
            func.count(Waste.id)
        ).filter(
            Waste.location_id.in_(location_ids),
            Waste.status == 'APROBADO',
            Waste.cancelled_at.is_(None),
            Waste.date >= desde,
            Waste.date <= hasta,
        ).scalar() or 0)

    if metric in ('KITCHEN_CONSUMPTION', 'CONSOLIDATED'):
        resumen = obtener_consumo_valorizado(location_ids, desde, hasta)['total']
        totales['amount_usd'] += resumen.get('USD', Decimal('0.00'))
        totales['amount_bs'] += resumen.get('BS', Decimal('0.00'))
        totales['amount_eur'] += resumen.get('EUR', Decimal('0.00'))
        totales['record_count'] += obtener_resumen_consumo(
            location_ids, desde, hasta)

    if metric in ('TRANSFERS', 'CONSOLIDATED'):
        datos = obtener_traslados_valorizados(location_ids, desde, hasta)
        for fila in datos['filas']:
            b = fila['buckets']
            totales['amount_usd'] += b.get('USD', Decimal('0.00'))
            totales['amount_bs'] += b.get('BS', Decimal('0.00'))
            totales['amount_eur'] += b.get('EUR', Decimal('0.00'))
            totales['quantity'] += fila['quantity']
        totales['record_count'] += len(datos['filas'])

    for clave in ('amount_usd', 'amount_bs', 'amount_eur', 'quantity'):
        totales[clave] = totales[clave].quantize(Decimal('0.01'))
    return totales


def hay_snapshots_metrico(location_ids, metric, period_type=None):
    """True si el cajón ya tiene injerencia para esta métrica (y tipo) y sedes."""
    if not location_ids:
        return False
    q = StatisticsSnapshot.query.filter(
        StatisticsSnapshot.location_id.in_(location_ids),
        StatisticsSnapshot.metric == metric)
    if period_type:
        q = q.filter(StatisticsSnapshot.period_type == period_type)
    return q.first() is not None


def obtener_nombres_sedes(location_ids):
    """Mapa {id: nombre} de las sedes dadas."""
    if not location_ids:
        return {}
    return dict(db.session.query(Location.id, Location.name).filter(
        Location.id.in_(location_ids)).all())


def fechas_con_registros(location_ids, metric):
    """Fechas con registros REALES (compras, consumo, mermas, traslados) para las
    sedes dadas, ascendentes y sin repetir. Son las únicas fechas que el rango
    desde/hasta permite elegir: solo los días que de verdad tienen datos."""
    if not location_ids:
        return []
    metric = (metric or '').upper()
    fechas = set()

    if metric in ('PURCHASES', 'CONSOLIDATED'):
        filas = db.session.query(Purchase.purchase_date).filter(
            func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
        ).distinct().all()
        fechas.update(fila[0].date() if hasattr(fila[0], 'date') else fila[0]
                      for fila in filas)

    if metric in ('KITCHEN_CONSUMPTION', 'CONSOLIDATED'):
        filas = db.session.query(AuditLog.timestamp).filter(
            AuditLog.location_id.in_(location_ids),
            AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
        ).distinct().all()
        fechas.update(fila[0].date() if hasattr(fila[0], 'date') else fila[0]
                      for fila in filas)

    if metric in ('WASTE', 'CONSOLIDATED'):
        filas = db.session.query(Waste.date).filter(
            Waste.location_id.in_(location_ids),
            Waste.status == 'APROBADO',
            Waste.cancelled_at.is_(None),
        ).distinct().all()
        fechas.update(fila[0].date() if hasattr(fila[0], 'date') else fila[0]
                      for fila in filas)

    if metric in ('TRANSFERS', 'CONSOLIDATED'):
        filas = db.session.query(Movement.date).filter(
            db.or_(Movement.origin_location_id.in_(location_ids),
                   Movement.destination_location_id.in_(location_ids)),
        ).distinct().all()
        fechas.update(fila[0].date() if hasattr(fila[0], 'date') else fila[0]
                      for fila in filas)

    return sorted(fechas)


def hay_snapshots_en_rango(location_ids, metric, period_type, period_start, period_end):
    if not location_ids:
        return False
    return db.session.query(StatisticsSnapshot.id).filter(
        StatisticsSnapshot.location_id.in_(location_ids),
        StatisticsSnapshot.metric == metric,
        StatisticsSnapshot.period_type == period_type,
        StatisticsSnapshot.period_start >= period_start,
        StatisticsSnapshot.period_start <= period_end,
    ).first() is not None


def obtener_compras_por_proveedor(desde, hasta):
    """Detalle de compras del rango agrupado por proveedor y mes (no son por sede:
    las compras entran a la sede central). Monto en la moneda original de la
    compra (total_usd/total_eur) y el BS registrado en price_bs con la tasa del
    día de la compra (total_bs)."""
    compras = Purchase.query.filter(
        Purchase.purchase_date >= desde,
        Purchase.purchase_date <= hasta,
        func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
    ).all()

    filas = {}
    for compra in compras:
        clave = (compra.supplier_id if compra.supplier_id else 0,
                 compra.purchase_date.strftime('%Y-%m'))
        fila = filas.setdefault(clave, {
            'supplier_id': compra.supplier_id,
            'supplier_name': compra.supplier.name if compra.supplier else 'Sin proveedor',
            'month': compra.purchase_date.strftime('%Y-%m'),
            'purchase_count': 0,
            'total_usd': Decimal('0.00'),
            'total_bs': Decimal('0.00'),
            'total_eur': Decimal('0.00'),
        })
        bs_registrado = Decimal('0.00')
        for detalle in compra.details:
            bs_registrado += (Decimal(str(detalle.quantity or 0))
                              * Decimal(str(detalle.price_bs or 0)))
        moneda = (compra.currency or 'USD').upper()
        if moneda in ('BS', 'VES', 'BS.', 'BSS'):
            fila['total_bs'] += bs_registrado
        elif moneda == 'EUR':
            fila['total_eur'] += Decimal(str(compra.total_amount or 0))
            fila['total_bs'] += bs_registrado
        else:
            fila['total_usd'] += Decimal(str(compra.total_amount or 0))
            fila['total_bs'] += bs_registrado
        fila['purchase_count'] += 1

    filas = list(filas.values())
    filas.sort(key=lambda f: (-float(f['total_usd']) - float(f['total_bs']) - float(f['total_eur']),
                              f['month']))
    return filas


def obtener_mermas_detalle(location_ids, desde, hasta):
    """Cada merma APROBADA del rango con su costo REAL exacto, tal cual existe en
    la cabecera del registro (sin agregar ni convertir)."""
    if not location_ids:
        return []
    filas_brutas = db.session.query(
        Waste.id,
        Waste.date,
        Location.name.label('sede'),
        WasteType.name.label('tipo'),
        Waste.notes,
        Waste.total_quantity,
        Waste.total_cost,
        Waste.currency,
    ).join(Location, Location.id == Waste.location_id).outerjoin(
        WasteType, WasteType.id == Waste.waste_type_id
    ).filter(
        Waste.location_id.in_(location_ids),
        Waste.status == 'APROBADO',
        Waste.cancelled_at.is_(None),
        Waste.date >= desde,
        Waste.date <= hasta,
    ).order_by(Waste.date.asc(), Waste.id.asc()).all()

    return [{
        'id': fid,
        'date': fecha,
        'sede': sede,
        'waste_type': tipo or '',
        'notes': notas,
        'quantity': Decimal(str(cantidad or 0)).quantize(Decimal('0.01')),
        'cost': Decimal(str(costo or 0)).quantize(Decimal('0.01')),
        'currency': (moneda or 'USD').upper(),
    } for fid, fecha, sede, tipo, notas, cantidad, costo, moneda in filas_brutas]


def obtener_mermas_resumen(location_ids, desde, hasta):
    """Totales REALES por moneda y por sede de las mermas aprobadas del rango."""
    if not location_ids:
        return {'total': {}, 'por_sede': {}}
    filas = db.session.query(
        Location.name.label('sede'),
        Waste.currency,
        func.coalesce(func.sum(Waste.total_cost), 0),
    ).join(Location, Location.id == Waste.location_id).filter(
        Waste.location_id.in_(location_ids),
        Waste.status == 'APROBADO',
        Waste.cancelled_at.is_(None),
        Waste.date >= desde,
        Waste.date <= hasta,
    ).group_by(Location.name, Waste.currency).all()

    total = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}
    por_sede = {}
    for sede, moneda, costo in filas:
        moneda = (moneda or 'USD').upper()
        monto = Decimal(str(costo or 0))
        if moneda not in total:
            total[moneda] = Decimal('0.00')
        total[moneda] += monto
        if sede not in por_sede:
            por_sede[sede] = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
                              'EUR': Decimal('0.00')}
        por_sede[sede][moneda] += monto

    for valores in por_sede.values():
        for clave in ('USD', 'BS', 'EUR'):
            valores[clave] = valores[clave].quantize(Decimal('0.01'))
    for clave in ('USD', 'BS', 'EUR'):
        total[clave] = total[clave].quantize(Decimal('0.01'))
    return {'total': total, 'por_sede': por_sede}


def _direccion(origen, destino, ids, orientacion_id=None):
    """Clasifica un movimiento según el punto de vista del usuario.
    Por defecto se orienta respecto a sus sedes (enviados/recibidos/internos);
    si se pasa orientacion_id (p. ej. la Central para el admin que la gestiona)
    un movimiento se considera 'enviado' cuando sale de esa sede y 'recibido'
    cuando entra en ella; el resto son internos."""
    if orientacion_id is not None:
        if origen == orientacion_id:
            return 'enviados'
        if destino == orientacion_id:
            return 'recibidos'
        return 'internos'
    if origen in ids and destino in ids:
        return 'internos'
    if origen in ids:
        return 'enviados'
    return 'recibidos'


def obtener_resumen_traslados(location_ids, desde, hasta, orientacion_id=None):
    """Conteos de traslados del rango: enviados/recibidos, por estado y por tipo.
    La valorización de extravíos (MovementDetail.missing_quantity) se hace con el
    contrato de valorización en la capa de servicio; aquí solo el conteo."""
    resumen_vacio = {
        'enviados': 0, 'recibidos': 0, 'internos': 0,
        'por_estado': {}, 'por_tipo': {},
        'reposiciones': 0, 'disputas': 0,
        'extravios_quantity': Decimal('0.00'),
    }
    if not location_ids:
        return resumen_vacio

    movimientos = Movement.query.filter(
        Movement.date >= desde,
        Movement.date <= hasta,
        db.or_(Movement.origin_location_id.in_(location_ids),
               Movement.destination_location_id.in_(location_ids)),
    ).all()

    resumen = dict(resumen_vacio)
    extravios = Decimal('0.00')
    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        direccion = _direccion(origen, destino, location_ids, orientacion_id)
        resumen[direccion] += 1

        tipo = (mov.type or 'OTROS').upper()
        resumen['por_tipo'][tipo] = resumen['por_tipo'].get(tipo, 0) + 1
        estado = (mov.status or 'OTROS').upper()
        resumen['por_estado'][estado] = resumen['por_estado'].get(estado, 0) + 1
        if mov.source_dispute_id is not None:
            resumen['reposiciones'] += 1
        if mov.status in ('NOVEDAD_FALTANTE', 'CERRADO_CON_PERDIDA',
                          'CERRADO_POR_ADMIN'):
            resumen['disputas'] += 1

        for detalle in mov.details:
            if detalle.missing_quantity:
                extravios += Decimal(str(detalle.missing_quantity))

    resumen['extravios_quantity'] = extravios.quantize(Decimal('0.01'))
    return resumen


def obtener_traslados_valorizados(location_ids, desde, hasta,
                                  orientacion_id=None):
    """Movimientos del rango con cantidad y costo REAL (último costo de compra
    por producto/lote, bucket a bucket según la moneda del precio), direccional
    respecto a las sedes del usuario:
      - enviados:  salen de sus sedes (origen ∈, destino ∉)
      - recibidos: entran a sus sedes (destino ∈, origen ∉)
      - internos:  se mueven entre sus sedes.
    Si se pasa orientacion_id (p. ej. la Central para quien la gestiona) la
    dirección se calcula desde esa sede: se narra lo que ella envía/recibe.
    Devuelve {'filas': [...]} con un dict por movimiento (id, date, type,
    status, direccion, origin_id, origin_name, destination_id,
    destination_name, quantity, missing_quantity, buckets, perdidas) y además
    'perdidas' (extravíos missing_quantity valorizados bucket a bucket) y
    'extravios_quantity'."""
    vacio = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}
    base = {'filas': [], 'perdidas': dict(vacio),
            'extravios_quantity': Decimal('0.00')}
    if not location_ids:
        return base

    ids = set(location_ids)
    nombres = dict(db.session.query(Location.id, Location.name).filter(
        Location.id.in_(ids)).all())

    def nombre_sede(loc_id):
        if loc_id in nombres:
            return nombres[loc_id]
        loc = db.session.get(Location, loc_id)
        return loc.name if loc is not None else 'Sede #{0}'.format(loc_id)

    movimientos = Movement.query.filter(
        Movement.date >= desde,
        Movement.date <= hasta,
        db.or_(Movement.origin_location_id.in_(ids),
               Movement.destination_location_id.in_(ids)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()

    perdidas = dict(vacio)
    extravios = Decimal('0.00')
    filas = []
    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        direccion = _direccion(origen, destino, ids, orientacion_id)

        buckets = dict(vacio)
        perdidas_mov = dict(vacio)
        cantidad = Decimal('0.00')
        faltante = Decimal('0.00')
        for detalle in mov.details:
            cantidad += Decimal(str(detalle.quantity or 0))
            precio, moneda = _ultimo_costo_compra(detalle.product_id,
                                                  detalle.lot_number)
            if moneda not in buckets:
                buckets[moneda] = Decimal('0.00')
            buckets[moneda] += Decimal(str(detalle.quantity or 0)) * precio
            if detalle.missing_quantity:
                falta = Decimal(str(detalle.missing_quantity))
                faltante += falta
                if moneda not in perdidas_mov:
                    perdidas_mov[moneda] = Decimal('0.00')
                perdidas_mov[moneda] += falta * precio

        for moneda in ('USD', 'BS', 'EUR'):
            buckets[moneda] = buckets.get(moneda, Decimal('0.00')).quantize(
                Decimal('0.01'))
            perdidas_mov[moneda] = perdidas_mov.get(
                moneda, Decimal('0.00')).quantize(Decimal('0.01'))
            perdidas[moneda] += perdidas_mov[moneda]
        extravios += faltante

        filas.append({
            'id': mov.id,
            'date': mov.date,
            'type': (mov.type or 'OTROS').upper(),
            'status': (mov.status or 'OTROS').upper(),
            'direccion': direccion,
            'origin_id': origen,
            'origin_name': nombre_sede(origen),
            'destination_id': destino,
            'destination_name': nombre_sede(destino),
            'quantity': cantidad.quantize(Decimal('0.01')),
            'missing_quantity': faltante.quantize(Decimal('0.01')),
            'buckets': dict(buckets),
            'perdidas': dict(perdidas_mov),
        })

    for moneda in ('USD', 'BS', 'EUR'):
        perdidas[moneda] = perdidas[moneda].quantize(Decimal('0.01'))
    return {
        'filas': filas,
        'perdidas': perdidas,
        'extravios_quantity': extravios.quantize(Decimal('0.01')),
    }


def obtener_recibido_por_insumo(location_ids, desde, hasta, orientacion_id=None):
    """Mercancía RECIBIDA del rango por insumo (producto) y por sede: qué
    llegó a cada sede de destino y en qué cantidad. Solo los movimientos que
    clasifican como 'recibidos' (destino ∈ sedes del usuario; con orientacion_id
    se narra desde esa sede). La cantidad efectiva usada es received_quantity
    (lo realmente llegado) o quantity a falta de registro.
    Devuelve {'detalle': fn(filas), 'top': fn} con:
      - detalle: fila por (sede, producto) ya agregada, ordenada por cantidad
        descendente: {sede_name, product_id, product_name, quantity, lots}.
      - top: agregación global por producto (todas las sedes) del mismo orden.
    """
    vacio = {'detalle': [], 'top': []}
    if not location_ids:
        return vacio

    ids = set(location_ids)
    nombres = dict(db.session.query(Location.id, Location.name).filter(
        Location.id.in_(ids)).all())

    def nombre_sede(loc_id):
        if loc_id in nombres:
            return nombres[loc_id]
        loc = db.session.get(Location, loc_id)
        return loc.name if loc is not None else 'Sede #{0}'.format(loc_id)

    movimientos = Movement.query.filter(
        Movement.date >= desde,
        Movement.date <= hasta,
        db.or_(Movement.origin_location_id.in_(ids),
               Movement.destination_location_id.in_(ids)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()

    # (sede_id, product_id) -> {'name', 'quantity', 'lots'}
    por_sede_producto = {}
    top = {}

    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        if _direccion(origen, destino, ids, orientacion_id) != 'recibidos':
            continue
        sede_id = destino
        for detalle in mov.details:
            cantidad = (Decimal(str(detalle.received_quantity or 0))
                        if detalle.received_quantity is not None
                        else Decimal(str(detalle.quantity or 0)))
            if not cantidad:
                continue
            producto = db.session.get(Product, detalle.product_id)
            nombre = producto.name if producto else 'Insumo #{0}'.format(
                detalle.product_id)
            clave = (sede_id, detalle.product_id)
            if clave not in por_sede_producto:
                por_sede_producto[clave] = {
                    'sede_name': nombre_sede(sede_id),
                    'product_id': detalle.product_id,
                    'product_name': nombre,
                    'quantity': Decimal('0.00'),
                    'lots': 0,
                }
            fila = por_sede_producto[clave]
            fila['quantity'] += cantidad
            fila['lots'] += 1
            if detalle.product_id not in top:
                top[detalle.product_id] = {
                    'product_id': detalle.product_id,
                    'product_name': nombre,
                    'quantity': Decimal('0.00'),
                }
            top[detalle.product_id]['quantity'] += cantidad

    def cuantizar(fila):
        fila['quantity'] = fila['quantity'].quantize(Decimal('0.01'))

    detalle = sorted(
        por_sede_producto.values(),
        key=lambda f: (-float(f['quantity']), f['sede_name'], f['product_name']))
    for fila in detalle:
        cuantizar(fila)
    top_lista = sorted(
        top.values(), key=lambda f: (-float(f['quantity']), f['product_name']))
    for fila in top_lista:
        cuantizar(fila)
    return {'detalle': detalle, 'top': top_lista}


def obtener_resumen_consumo(location_ids, desde, hasta):
    """Cantidad de registros de consumo de cocina del rango desde la auditoría.
    La valorización (cantidad × último precio) se hace con el contrato de
    valorización en la capa de servicio; aquí solo el conteo."""
    if not location_ids:
        return 0
    return int(db.session.query(func.count(AuditLog.id)).filter(
        AuditLog.location_id.in_(location_ids),
        AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
        AuditLog.timestamp >= desde,
        AuditLog.timestamp <= hasta,
    ).scalar() or 0)


def obtener_gasto_por_categoria(desde, hasta, moneda='USD', conversor=None):
    """Gasto REAL por categoría contable, directamente desde purchase_details
    (cantidad × precio). Montos exactos en la moneda original de cada compra:
    bucket a bucket (USD/BS/EUR), sin conversión. El BS de cada detalle es el
    price_bs registrado (tasa del día de la compra)."""
    compras = Purchase.query.filter(
        Purchase.purchase_date >= desde,
        Purchase.purchase_date <= hasta,
        func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
    ).all()

    filas = {}
    for compra in compras:
        mes = compra.purchase_date.strftime('%Y-%m')
        moneda_orig = (compra.currency or 'USD').upper()
        for detalle in compra.details:
            producto = db.session.get(Product, detalle.product_id)
            categoria = 'Sin categoría'
            if producto is not None and producto.product_type is not None:
                macro = producto.product_type.category
                categoria = macro.name if macro is not None else 'Sin categoría'
            fila = filas.setdefault((mes, categoria), {
                'month': mes, 'category': categoria,
                'total_usd': Decimal('0.00'),
                'total_bs': Decimal('0.00'),
                'total_eur': Decimal('0.00'),
            })
            cantidad = Decimal(str(detalle.quantity or 0))
            if moneda_orig in ('BS', 'VES', 'BS.', 'BSS'):
                monto = cantidad * Decimal(str(detalle.price_bs or 0))
                fila['total_bs'] += monto
            elif moneda_orig == 'EUR':
                monto = cantidad * Decimal(str(detalle.foreign_price or 0))
                fila['total_eur'] += monto
                fila['total_bs'] += cantidad * Decimal(str(detalle.price_bs or 0))
            else:
                monto = cantidad * Decimal(str(detalle.foreign_price or 0))
                fila['total_usd'] += monto
                fila['total_bs'] += cantidad * Decimal(str(detalle.price_bs or 0))

    filas = list(filas.values())
    for fila in filas:
        for clave in ('total_usd', 'total_bs', 'total_eur'):
            fila[clave] = fila[clave].quantize(Decimal('0.01'))
    filas.sort(key=lambda f: (-float(f['total_usd']), f['month']))
    return filas


def obtener_tasa_historica(moneda, fecha):
    """Tasa BCV (Bs por unidad de 'moneda') vigente en 'fecha': el registro de
    ExchangeRateHistory más reciente con timestamp <= fecha. None si no hay."""
    q = db.session.query(ExchangeRateHistory.rate).filter(
        ExchangeRateHistory.currency == (moneda or 'USD').upper(),
        ExchangeRateHistory.timestamp <= fecha,
    ).order_by(ExchangeRateHistory.timestamp.desc())
    fila = q.first()
    if fila is None or fila[0] is None:
        return None
    try:
        return Decimal(str(fila[0]))
    except (TypeError, ValueError):
        return None


def _ultimo_costo_compra(product_id, lot_number=None):
    """Último costo de compra (foreign_price) del lote exacto; a falta de este,
    del producto. Retorna (precio Decimal, moneda)."""
    def consulta(lote):
        q = db.session.query(
            PurchaseDetail.foreign_price, Purchase.currency
        ).join(Purchase, PurchaseDetail.purchase_id == Purchase.id).filter(
            func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
            PurchaseDetail.product_id == int(product_id),
        )
        if lote:
            q = q.filter(PurchaseDetail.lot_number == str(lote).strip())
        return q.order_by(PurchaseDetail.id.desc()).first()

    fila = consulta(lot_number)
    if fila is None and lot_number:
        fila = consulta(None)
    if fila is None or fila[0] is None:
        return Decimal('0.00'), 'USD'
    return Decimal(str(fila[0])), (fila[1] or 'USD').upper()


def obtener_consumo_valorizado(location_ids, desde, hasta):
    """Gasto REAL de cocina del rango: cantidad consumida por la auditoría
    (GASTO_COCINA/CONSUMO_COCINA) × último costo de compra, bucket a bucket por
    la moneda del precio. Sin tasas ni conversión."""
    vacio = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}
    if not location_ids:
        return {'total': dict(vacio), 'por_sede': {}}

    nombres = dict(db.session.query(Location.id, Location.name).filter(
        Location.id.in_(location_ids)).all())
    total = dict(vacio)
    por_sede = {}

    registros = db.session.query(AuditLog.location_id, AuditLog.changed_data).filter(
        AuditLog.location_id.in_(location_ids),
        AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
        AuditLog.timestamp >= desde,
        AuditLog.timestamp <= hasta,
    ).all()

    for loc_id, c_data in registros:
        if not c_data:
            continue
        if isinstance(c_data, str):
            try:
                c_data = json.loads(c_data)
            except Exception:
                continue
        if not isinstance(c_data, dict):
            continue
        try:
            p_id = int(c_data.get('product_id')) if c_data.get('product_id') is not None else None
        except (TypeError, ValueError):
            p_id = None
        l_num = c_data.get('lot_number')
        if not l_num or str(l_num).strip() in ('', 'N/A'):
            l_num = None
        # Cantidad efectiva: si el gasto fue editado/anulado/reactivado, el
        # movimiento compensatorio deja 'edited_quantity' en el log original.
        # Se usa esa magnitud (con signo de egreso) para reflejar el gasto REAL
        # corregido y no la cantidad original ya reemplazada.
        if c_data.get('edited_quantity') is not None:
            try:
                cantidad = -abs(Decimal(str(c_data.get('edited_quantity'))))
            except (TypeError, ValueError):
                cantidad = Decimal('0.00')
        else:
            try:
                cantidad = Decimal(str(c_data.get('quantity_changed', 0.0) or 0.0))
            except (TypeError, ValueError):
                cantidad = Decimal('0.00')
        if p_id is None or not cantidad:
            continue

        precio, moneda = _ultimo_costo_compra(p_id, l_num)
        monto = (cantidad * precio).quantize(Decimal('0.01'))
        if moneda not in total:
            total[moneda] = Decimal('0.00')
        total[moneda] += monto
        sede = nombres.get(loc_id, f'Sede {loc_id}')
        if sede not in por_sede:
            por_sede[sede] = dict(vacio)
        if moneda not in por_sede[sede]:
            por_sede[sede][moneda] = Decimal('0.00')
        por_sede[sede][moneda] += monto

    for clave in ('USD', 'BS', 'EUR'):
        total[clave] = total[clave].quantize(Decimal('0.01'))
    for sede in por_sede:
        for clave in ('USD', 'BS', 'EUR'):
            por_sede[sede][clave] = por_sede[sede][clave].quantize(Decimal('0.01'))
    return {'total': total, 'por_sede': por_sede}


def obtener_compras_consolidado(desde, hasta):
    """Líneas REALES de compras del rango (cantidad × precio, categoría contable y
    moneda original). El gasto por compra pertenece a la sede Central."""
    linea_vacia = {
        'buckets': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')},
        'category': 'Sin categoría', 'month': '',
    }
    agrupadas = {}
    compras = Purchase.query.filter(
        Purchase.purchase_date >= desde,
        Purchase.purchase_date <= hasta,
        func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
    ).all()
    for compra in compras:
        moneda_orig = (compra.currency or 'USD').upper()
        mes = compra.purchase_date.strftime('%Y-%m')
        for detalle in compra.details:
            producto = db.session.get(Product, detalle.product_id)
            categoria = 'Sin categoría'
            if producto is not None and producto.product_type is not None:
                macro = producto.product_type.category
                categoria = macro.name if macro is not None else 'Sin categoría'
            clave = (mes, categoria)
            if clave not in agrupadas:
                agrupadas[clave] = {
                    'month': mes, 'category': categoria,
                    'buckets': dict(linea_vacia['buckets']),
                }
            cantidad = Decimal(str(detalle.quantity or 0))
            if moneda_orig in ('BS', 'VES', 'BS.', 'BSS'):
                bucket = 'BS'
                monto = cantidad * Decimal(str(detalle.price_bs or 0))
            elif moneda_orig == 'EUR':
                bucket = 'EUR'
                monto = cantidad * Decimal(str(detalle.foreign_price or 0))
            else:
                bucket = 'USD'
                monto = cantidad * Decimal(str(detalle.foreign_price or 0))
            agrupadas[clave]['buckets'][bucket] += monto
            if bucket != 'BS':
                # El BS registrado en price_bs se grabó con la tasa del día de la
                # compra (Purchase.exchange_rate), no con la del cierre del período.
                agrupadas[clave]['buckets']['BS'] += (
                    cantidad * Decimal(str(detalle.price_bs or 0)))

    for fila in agrupadas.values():
        for clave in ('USD', 'BS', 'EUR'):
            fila['buckets'][clave] = fila['buckets'][clave].quantize(Decimal('0.01'))
    return list(agrupadas.values())


def obtener_compras_por_moneda(desde, hasta):
    """Una fila por compra completada del rango con su moneda, la tasa del día
    que el sistema guardó al registrarla (Purchase.exchange_rate; si no está
    guardada se usa la última tasa BCV del día de la compra) y los totales por
    moneda con el VALOR REGISTRADO: el BS de cada detalle es cantidad × price_bs
    (grabado con esa tasa del día de la compra)."""
    compras = Purchase.query.filter(
        Purchase.purchase_date >= desde,
        Purchase.purchase_date <= hasta,
        func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
    ).all()
    filas = []
    for compra in compras:
        moneda = (compra.currency or 'USD').upper()
        tasa = Decimal(str(compra.exchange_rate or 0))
        if not tasa:
            tasa = obtener_tasa_historica(moneda, compra.purchase_date) or Decimal('0.00')
        total_usd = total_bs = total_eur = Decimal('0.00')
        for detalle in compra.details:
            cantidad = Decimal(str(detalle.quantity or 0))
            total_bs += cantidad * Decimal(str(detalle.price_bs or 0))
            if moneda == 'EUR':
                total_eur += cantidad * Decimal(str(detalle.foreign_price or 0))
            elif moneda in ('BS', 'VES', 'BS.', 'BSS'):
                pass
            else:
                total_usd += cantidad * Decimal(str(detalle.foreign_price or 0))
        filas.append({
            'currency': moneda,
            'purchase_date': compra.purchase_date,
            'exchange_rate': tasa,
            'total_usd': total_usd.quantize(Decimal('0.01')),
            'total_bs': total_bs.quantize(Decimal('0.01')),
            'total_eur': total_eur.quantize(Decimal('0.01')),
        })
    return filas