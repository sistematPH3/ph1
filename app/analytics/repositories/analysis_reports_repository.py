import json
import logging
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.security_model import User
from app.models.statistics_model import StatisticsSnapshot
from app.models.logistics_model import (ExchangeRateHistory, Location, Purchase,
                                         PurchaseDetail, Movement, MovementDetail)
from app.models.inventory_model import Product
from app.models.waste_model import AuditLog, Waste, WasteDetail, WasteType

logger = logging.getLogger(__name__)


# Estados de un movimiento que nunca entran a las estadísticas: el traslado
# fue cancelado, anulado o rechazado, así que la mercancía no se movió.
ESTADOS_TRASLADO_ANULADOS = (
    'CANCELADO', 'CANCELADO_EMISOR', 'ANULADO', 'RECHAZADO',
)
# Un movimiento EN_TRANSITO ya salió de origen (cuenta como enviado) pero aún
# no ha llegado a destino (no cuenta como recibido ni interno).
ESTADOS_TRASLADO_EN_TRANSITO = ('EN_TRANSITO',)
# Devoluciones: NO son traslados de abastecimiento. Los traslados que cuentan
# para las estadísticas son solo los consolidados (despachos); los retornos
# se informan aparte como devoluciones al Almacén Central.
TIPOS_TRASLADO_DEVOLUCION = ('DEVOLUCION', 'RETORNO_EMERGENCIA')
ESTADOS_TRASLADO_DEVUELTOS = ('DEVUELTO', 'DEVUELTA', 'DEVOLUCION',
                              'RETORNO_EMERGENCIA')


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


def _rango_datetime(desde, hasta):
    """Normaliza el rango a datetimes que cubren los días COMPLETOS: `desde` a
    las 00:00:00 y `hasta` a las 23:59:59.999999. Sin esto, una fecha `hasta`
    (00:00) dejaba fuera los registros del propio día que ocurrieron más tarde."""
    desde_dt = (desde if isinstance(desde, datetime)
                else datetime.combine(desde, time.min))
    hasta_dt = (hasta if isinstance(hasta, datetime)
                else datetime.combine(hasta, time.max))
    return desde_dt, hasta_dt


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
    desde, hasta = _rango_datetime(desde, hasta)

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
    compra (total_usd/total_eur) y el BS registrado con la tasa del día de la
    compra (total_bs), ambos desde la cabecera de la factura.

    'equivalente' trae el monto valorizado en las tres monedas con la TASA DEL
    DÍA de cada compra (no con la tasa de cierre del período), para que el
    detalle por proveedor cuadre al céntimo con el KPI de compras."""
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
            'equivalente': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
                            'EUR': Decimal('0.00')},
        })
        moneda = (compra.currency or 'USD').upper()
        bucket = ('BS' if moneda in ('BS', 'VES', 'BS.', 'BSS')
                  else ('EUR' if moneda == 'EUR' else 'USD'))
        total_real = _total_real_compra(compra)
        total_bs_real = _total_bs_compra(compra, moneda, total_real)
        fila['total_bs'] += total_bs_real
        if bucket != 'BS':
            fila['total_' + bucket.lower()] += total_real

        # Equivalente con la tasa del día de la compra (misma base que
        # _compras_en_moneda); antes se reconvertía con la tasa de cierre.
        fila['equivalente'][bucket] += total_real
        if bucket != 'BS':
            fila['equivalente']['BS'] += total_bs_real
        if bucket == 'USD':
            tasa_eur = obtener_tasa_historica('EUR', compra.purchase_date)
            if tasa_eur:
                fila['equivalente']['EUR'] += total_bs_real / tasa_eur
        elif bucket == 'EUR':
            tasa_usd = obtener_tasa_historica('USD', compra.purchase_date)
            if tasa_usd:
                fila['equivalente']['USD'] += total_bs_real / tasa_usd
        else:
            tasa_usd = (Decimal(str(compra.exchange_rate or 0))
                        or obtener_tasa_historica('USD',
                                                  compra.purchase_date))
            tasa_eur = obtener_tasa_historica('EUR', compra.purchase_date)
            if tasa_usd:
                fila['equivalente']['USD'] += total_real / tasa_usd
            if tasa_eur:
                fila['equivalente']['EUR'] += total_real / tasa_eur
        fila['purchase_count'] += 1

    filas = list(filas.values())
    for fila in filas:
        for clave_moneda in ('USD', 'BS', 'EUR'):
            fila['equivalente'][clave_moneda] = (
                fila['equivalente'][clave_moneda].quantize(Decimal('0.01')))
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


def obtener_mermas_top_producto(location_ids, desde, hasta):
    """Mermas APROBADAS del rango agrupadas por PRODUCTO: cantidad mermada y su
    costo por moneda (buckets disjuntos), para identificar el producto de mayor
    impacto. Se toman las líneas (waste_details) de las cabeceras aprobadas, de
    modo que el detalle suma lo mismo que la cabecera del ticket."""
    if not location_ids:
        return []
    desde, hasta = _rango_datetime(desde, hasta)
    filas = db.session.query(
        WasteDetail.product_id,
        Product.name.label('producto'),
        Waste.currency,
        func.coalesce(func.sum(WasteDetail.quantity), 0),
        func.coalesce(func.sum(WasteDetail.subtotal_cost), 0),
    ).join(Waste, Waste.id == WasteDetail.waste_id).outerjoin(
        Product, Product.id == WasteDetail.product_id
    ).filter(
        Waste.location_id.in_(location_ids),
        Waste.status == 'APROBADO',
        Waste.cancelled_at.is_(None),
        Waste.date >= desde,
        Waste.date <= hasta,
    ).group_by(WasteDetail.product_id, Product.name, Waste.currency).all()

    agrupado = {}
    for product_id, nombre, moneda, cantidad, costo in filas:
        clave = product_id if product_id is not None else -1
        fila = agrupado.setdefault(clave, {
            'product_id': product_id,
            'product_name': nombre or 'Producto #{0}'.format(product_id),
            'quantity': Decimal('0.00'),
            'buckets': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
                        'EUR': Decimal('0.00')},
        })
        moneda = (moneda or 'USD').upper()
        if moneda in ('VES', 'BS.', 'BSS', 'BOLIVARES', 'BOLÍVARES'):
            moneda = 'BS'
        if moneda not in fila['buckets']:
            fila['buckets'][moneda] = Decimal('0.00')
        fila['quantity'] += Decimal(str(cantidad or 0))
        fila['buckets'][moneda] += Decimal(str(costo or 0))

    for fila in agrupado.values():
        fila['quantity'] = fila['quantity'].quantize(Decimal('0.01'))
        for clave in fila['buckets']:
            fila['buckets'][clave] = fila['buckets'][clave].quantize(
                Decimal('0.01'))
    return list(agrupado.values())


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
        db.or_(Movement.status.is_(None),
               Movement.status.notin_(ESTADOS_TRASLADO_ANULADOS)),
        db.or_(Movement.origin_location_id.in_(location_ids),
               Movement.destination_location_id.in_(location_ids)),
    ).all()

    resumen = dict(resumen_vacio)
    extravios = Decimal('0.00')
    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        direccion = _direccion(origen, destino, location_ids, orientacion_id)
        estado = (mov.status or 'OTROS').upper()
        # Un traslado en tránsito ya salió, pero no se ha recibido: solo
        # cuenta como enviado.
        if (direccion != 'enviados'
                and estado in ESTADOS_TRASLADO_EN_TRANSITO):
            continue
        resumen[direccion] += 1

        tipo = (mov.type or 'OTROS').upper()
        resumen['por_tipo'][tipo] = resumen['por_tipo'].get(tipo, 0) + 1
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
    La    La cantidad y el costo se miden según la dirección: quien envía reporta lo
    despachado; quien recibe (o un traslado interno, donde el usuario es origen
    y destino) reporta lo realmente llegado (received_quantity; sin recepción
    registrada no hay mercancía llegada). Las devoluciones/retornos se excluyen:
    no son traslados de abastecimiento (se informan con
    obtener_devoluciones_central).    Devuelve {'filas': [...]} con un dict por movimiento (id, date, type,
    status, direccion, origin_id, origin_name, destination_id,
    destination_name, quantity, despachado, missing_quantity, buckets,
    buckets_despachado, perdidas) y además 'perdidas' (extravíos
    missing_quantity valorizados bucket a bucket), 'extravios_quantity' y
    'perdidas_detalle' (una fila por producto perdido: qué se perdió y cuánto).
"""
    vacio = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}
    base = {'filas': [], 'perdidas': dict(vacio),
            'extravios_quantity': Decimal('0.00'),
            'perdidas_detalle': []}
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
        # Solo traslados consolidados: las devoluciones/retornos se informan
        # aparte (devoluciones al Almacén Central) y no inflan lo trasladado.
        Movement.type.notin_(TIPOS_TRASLADO_DEVOLUCION),
        db.or_(Movement.status.is_(None),
               Movement.status.notin_(ESTADOS_TRASLADO_ANULADOS
                                      + ESTADOS_TRASLADO_DEVUELTOS)),
        db.or_(Movement.origin_location_id.in_(ids),
               Movement.destination_location_id.in_(ids)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()

    perdidas = dict(vacio)
    extravios = Decimal('0.00')
    perdidas_detalle = []
    filas = []
    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        direccion = _direccion(origen, destino, ids, orientacion_id)
        estado = (mov.status or 'OTROS').upper()
        # Un traslado en tránsito salió de origen pero aún no ha llegado: cuenta
        # como enviado, pero no como recibido ni interno (ni sus pérdidas, que
        # solo pueden registrarse al recibir).
        cuenta_direccion = not (
            direccion != 'enviados' and estado in ESTADOS_TRASLADO_EN_TRANSITO
        )

        buckets = dict(vacio)
        buckets_despachado = dict(vacio)
        buckets_recibido = dict(vacio)
        perdidas_mov = dict(vacio)
        cantidad = Decimal('0.00')
        cantidad_despachada = Decimal('0.00')
        cantidad_recibida = Decimal('0.00')
        faltante = Decimal('0.00')
        for detalle in mov.details:
            despachada = Decimal(str(detalle.quantity or 0))
            # Lo realmente recepcionado en destino, sin importar la dirección
            # con la que se narre el movimiento (un despacho desde la Central
            # también es mercancía recibida por la sucursal). NULL = no llegó.
            recibida = (Decimal(str(detalle.received_quantity))
                        if detalle.received_quantity is not None
                        else Decimal('0.00'))
            cantidad_recibida += recibida
            # Enviados: lo que salió. Recibidos e internos: lo que llegó. Si no
            # hay recepción registrada (received_quantity NULL) no llegó nada.
            if direccion == 'enviados':
                efectiva = despachada
            else:
                efectiva = (Decimal(str(detalle.received_quantity))
                            if detalle.received_quantity is not None
                            else Decimal('0.00'))
            if not cuenta_direccion:
                efectiva = Decimal('0.00')
            cantidad += efectiva
            cantidad_despachada += despachada
            precio, moneda = _ultimo_costo_compra(detalle.product_id,
                                                  detalle.lot_number)
            if moneda not in buckets:
                buckets[moneda] = Decimal('0.00')
            buckets[moneda] += efectiva * precio
            if moneda not in buckets_despachado:
                buckets_despachado[moneda] = Decimal('0.00')
            buckets_despachado[moneda] += despachada * precio
            if moneda not in buckets_recibido:
                buckets_recibido[moneda] = Decimal('0.00')
            buckets_recibido[moneda] += recibida * precio
            if detalle.missing_quantity and cuenta_direccion:
                falta = Decimal(str(detalle.missing_quantity))
                faltante += falta
                if moneda not in perdidas_mov:
                    perdidas_mov[moneda] = Decimal('0.00')
                perdidas_mov[moneda] += falta * precio
                producto = db.session.get(Product, detalle.product_id)
                perdidas_detalle.append({
                    'detail_id': detalle.id,
                    'movement_id': mov.id,
                    'date': mov.date,
                    'type': (mov.type or 'OTROS').upper(),
                    'status': estado,
                    'origin_id': origen,
                    'origin_name': nombre_sede(origen),
                    'destination_id': destino,
                    'destination_name': nombre_sede(destino),
                    'product_id': detalle.product_id,
                    'product_name': (producto.name if producto is not None
                                     else 'Insumo #{0}'.format(
                                         detalle.product_id)),
                    'lot_number': detalle.lot_number,
                    'quantity': falta.quantize(Decimal('0.01')),
                    'buckets': {moneda: (falta * precio).quantize(
                        Decimal('0.01'))},
                })

        for moneda in ('USD', 'BS', 'EUR'):
            buckets[moneda] = buckets.get(moneda, Decimal('0.00')).quantize(
                Decimal('0.01'))
            buckets_despachado[moneda] = buckets_despachado.get(
                moneda, Decimal('0.00')).quantize(Decimal('0.01'))
            buckets_recibido[moneda] = buckets_recibido.get(
                moneda, Decimal('0.00')).quantize(Decimal('0.01'))
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
            'cuenta_direccion': cuenta_direccion,
            'quantity': cantidad.quantize(Decimal('0.01')),
            'despachado': cantidad_despachada.quantize(Decimal('0.01')),
            'received_quantity': cantidad_recibida.quantize(Decimal('0.01')),
            'missing_quantity': faltante.quantize(Decimal('0.01')),
            'buckets': dict(buckets),
            'buckets_despachado': dict(buckets_despachado),
            'buckets_recibido': dict(buckets_recibido),
            'perdidas': dict(perdidas_mov),
        })

    # Pérdidas ocurridas en DEVOLUCIONES/RETORNOS: el movimiento no suma al
    # volumen de traslados de abastecimiento, pero la mercancía perdida SÍ es
    # una pérdida real y debe aparecer en el detalle (antes el resumen la
    # contaba y la tabla la omitía). Se excluyen los movimientos anulados.
    devoluciones = Movement.query.filter(
        Movement.date >= desde,
        Movement.date <= hasta,
        Movement.type.in_(TIPOS_TRASLADO_DEVOLUCION),
        db.or_(Movement.status.is_(None),
               Movement.status.notin_(ESTADOS_TRASLADO_ANULADOS)),
        db.or_(Movement.origin_location_id.in_(ids),
               Movement.destination_location_id.in_(ids)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()
    for mov in devoluciones:
        for detalle in mov.details:
            if not detalle.missing_quantity:
                continue
            falta = Decimal(str(detalle.missing_quantity))
            precio, moneda = _ultimo_costo_compra(detalle.product_id,
                                                  detalle.lot_number)
            if moneda not in perdidas:
                perdidas[moneda] = Decimal('0.00')
            perdidas[moneda] += falta * precio
            extravios += falta
            producto = db.session.get(Product, detalle.product_id)
            perdidas_detalle.append({
                'detail_id': detalle.id,
                'movement_id': mov.id,
                'date': mov.date,
                'type': (mov.type or 'OTROS').upper(),
                'status': (mov.status or 'OTROS').upper(),
                'origin_id': mov.origin_location_id,
                'origin_name': nombre_sede(mov.origin_location_id),
                'destination_id': mov.destination_location_id,
                'destination_name': nombre_sede(mov.destination_location_id),
                'product_id': detalle.product_id,
                'product_name': (producto.name if producto is not None
                                 else 'Insumo #{0}'.format(detalle.product_id)),
                'lot_number': detalle.lot_number,
                'quantity': falta.quantize(Decimal('0.01')),
                'buckets': {moneda: (falta * precio).quantize(
                    Decimal('0.01'))},
            })

    for moneda in ('USD', 'BS', 'EUR'):
        perdidas[moneda] = perdidas[moneda].quantize(Decimal('0.01'))
    return {
        'filas': filas,
        'perdidas': perdidas,
        'extravios_quantity': extravios.quantize(Decimal('0.01')),
        'perdidas_detalle': perdidas_detalle,
    }


def obtener_devoluciones_central(location_ids, desde, hasta, central_id=1):
    """Devoluciones del período que llegaron (o van) al Almacén Central.

    No se mezclan con los traslados consolidados: aquí se valoriza la
    mercancía devuelta por cada sede. Se usa la cantidad recepcionada si ya
    fue procesada; si el retorno sigue en tránsito se valoriza lo despachado
    (la mercancía ya salió de la sede). Los movimientos anulados se omiten.
    Devuelve {'conteo', 'quantity', 'buckets', 'por_sede': {nombre: {...}}}.
    """
    vacio = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
             'EUR': Decimal('0.00')}
    base = {'conteo': 0, 'quantity': Decimal('0.00'),
            'buckets': dict(vacio), 'por_sede': {}}
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
        Movement.type.in_(TIPOS_TRASLADO_DEVOLUCION),
        Movement.destination_location_id == central_id,
        Movement.origin_location_id.in_(ids),
        db.or_(Movement.status.is_(None),
               Movement.status.notin_(ESTADOS_TRASLADO_ANULADOS)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()

    for mov in movimientos:
        sede = nombre_sede(mov.origin_location_id)
        ag = base['por_sede'].setdefault(sede, {
            'conteo': 0, 'quantity': Decimal('0.00'),
            'buckets': dict(vacio)})
        base['conteo'] += 1
        ag['conteo'] += 1
        for detalle in mov.details:
            if detalle.received_quantity is not None:
                efectiva = Decimal(str(detalle.received_quantity))
            else:
                efectiva = Decimal(str(detalle.quantity or 0))
            base['quantity'] += efectiva
            ag['quantity'] += efectiva
            precio, moneda = _ultimo_costo_compra(detalle.product_id,
                                                  detalle.lot_number)
            if moneda not in base['buckets']:
                base['buckets'][moneda] = Decimal('0.00')
            if moneda not in ag['buckets']:
                ag['buckets'][moneda] = Decimal('0.00')
            base['buckets'][moneda] += efectiva * precio
            ag['buckets'][moneda] += efectiva * precio

    for moneda in ('USD', 'BS', 'EUR'):
        base['buckets'][moneda] = base['buckets'][moneda].quantize(
            Decimal('0.01'))
        for ag in base['por_sede'].values():
            ag['buckets'][moneda] = ag['buckets'][moneda].quantize(
                Decimal('0.01'))
    for ag in base['por_sede'].values():
        ag['quantity'] = ag['quantity'].quantize(Decimal('0.01'))
    base['quantity'] = base['quantity'].quantize(Decimal('0.01'))
    return base


def obtener_recibido_por_insumo(location_ids, desde, hasta):
    """Mercancía RECIBIDA del rango por insumo (producto) y por sede: qué
    llegó a cada sede de destino visible y en qué cantidad. Se cuentan todos
    los movimientos cuyo DESTINO está entre las sedes consultadas (sin
    importar la orientación del flujo): así el Admin ve lo recibido por sus
    sucursales aunque la Central sea el origen. La cantidad efectiva usada es
    received_quantity (lo realmente llegado); si no hay recepción registrada
    (NULL) no se cuenta como mercancía recibida, aunque el movimiento tenga
    cantidad despachada. Los movimientos cancelados y los que siguen en
    tránsito se excluyen.
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
        db.or_(Movement.status.is_(None),
               Movement.status.notin_(ESTADOS_TRASLADO_ANULADOS
                                      + ESTADOS_TRASLADO_EN_TRANSITO)),
        db.or_(Movement.origin_location_id.in_(ids),
               Movement.destination_location_id.in_(ids)),
    ).order_by(Movement.date.asc(), Movement.id.asc()).all()

    # (sede_id, product_id) -> {'name', 'quantity', 'lots'}
    por_sede_producto = {}
    top = {}

    for mov in movimientos:
        origen, destino = mov.origin_location_id, mov.destination_location_id
        # Solo cuenta lo que llega a una sede visible; lo que sale hacia
        # fuera del ámbito consultado no es mercancía recibida.
        if destino not in ids:
            continue
        sede_id = destino
        for detalle in mov.details:
            # Sin recepción registrada no llegó mercancía: no se usa lo
            # despachado como respaldo.
            cantidad = (Decimal(str(detalle.received_quantity))
                        if detalle.received_quantity is not None
                        else Decimal('0.00'))
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
    """Gasto REAL por categoría contable desde las compras del rango.

    Cada fila sale de la CABECERA de la compra (importe exacto de la factura)
    repartido entre sus categorías y valorizado con la TASA DEL DÍA de compra,
    igual que el KPI de compras. Antes se reconstruía con cantidad × precio
    unitario: el precio redondeado a 2 decimales convertía 100,00 EUR en
    100,80 EUR / 101.715,20 Bs, y el servicio reconvertía ese Bs con la tasa de
    cierre del período (110,71 USD en vez de 109,95 USD).
    """
    filas = []
    for linea in obtener_compras_consolidado(desde, hasta):
        buckets = linea['buckets_equivalentes']
        filas.append({
            'month': linea['month'],
            'category': linea['category'],
            'total_usd': buckets['USD'],
            'total_bs': buckets['BS'],
            'total_eur': buckets['EUR'],
            # Monto del tramo en la moneda pedida, valorizado con la tasa del
            # día de cada compra (sin reconversiones posteriores).
            'equivalente': dict(linea['equivalente']),
        })
    filas.sort(key=lambda f: (-float(f['total_usd']), f['month']))
    return filas


def obtener_tasa_historica(moneda, fecha):
    """Tasa BCV (Bs por unidad de 'moneda') vigente en 'fecha': el registro de
    ExchangeRateHistory más reciente con timestamp <= fecha. Si no hay ninguno
    en o antes de la fecha, usa el registro MÁS ANTIGUO disponible de esa moneda
    (coherencia histórica: una fecha previa al primer registro no debe valorarse
    con una tasa futura). None solo si esa moneda no tiene ningún registro."""
    currency = (moneda or 'USD').upper()
    # Los registros viejos de bolívares usan 'VES'/'BS.'; las tasas se guardan
    # como 'BS', así que se homologa antes de consultar.
    if currency in ('VES', 'BS.', 'BSS', 'BOLIVARES', 'BOLÍVARES'):
        currency = 'BS'
    fila = db.session.query(ExchangeRateHistory.rate).filter(
        ExchangeRateHistory.currency == currency,
        ExchangeRateHistory.timestamp <= fecha,
    ).order_by(ExchangeRateHistory.timestamp.desc()).first()
    if fila is None:
        fila = db.session.query(ExchangeRateHistory.rate).filter(
            ExchangeRateHistory.currency == currency,
        ).order_by(ExchangeRateHistory.timestamp.asc()).first()
    if fila is None or fila[0] is None:
        return None
    try:
        return Decimal(str(fila[0]))
    except (TypeError, ValueError):
        return None


def _moneda_costo(moneda):
    """Homologa la moneda del precio a USD/BS/EUR. Las compras viejas guardan
    los bolívares como 'VES'/'BSS'/'BS.'; si el bucket conservara ese código,
    la valorización (que solo suma USD/BS/EUR) descartaría la pérdida."""
    codigo = (moneda or 'USD').upper()
    if codigo in ('VES', 'BS.', 'BSS', 'BOLIVARES', 'BOLÍVARES'):
        return 'BS'
    return codigo


def _ultimo_costo_compra(product_id, lot_number=None):
    """Último costo de compra (foreign_price) del lote exacto; a falta de este,
    del producto. Retorna (precio Decimal, moneda normalizada)."""
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
    return Decimal(str(fila[0])), _moneda_costo(fila[1])


def obtener_consumo_valorizado(location_ids, desde, hasta):
    """Gasto REAL de cocina del rango: cantidad consumida por la auditoría
    (GASTO_COCINA/CONSUMO_COCINA) × último costo de compra, bucket a bucket por
    la moneda del precio. Sin tasas ni conversión. Además devuelve
    'por_producto': la misma valorización agrupada por insumo, para conocer el
    producto que encabeza el consumo."""
    vacio = {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')}
    if not location_ids:
        return {'total': dict(vacio), 'por_sede': {}, 'por_producto': []}

    nombres = dict(db.session.query(Location.id, Location.name).filter(
        Location.id.in_(location_ids)).all())
    total = dict(vacio)
    por_sede = {}
    por_producto = {}

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
            except Exception as exc:
                logger.warning(
                    "Registro de auditoría con JSON inválido; se omite la fila: %s",
                    exc,
                )
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
        # Se usa esa magnitud para reflejar el gasto REAL corregido. El signo
        # negativo es solo la convención del kardex (register_consumption
        # guarda -abs(...)); el reporte necesita la MAGNITUD positiva para que
        # el consolidado no invierta la resta de egresos.
        if c_data.get('edited_quantity') is not None:
            try:
                cantidad = abs(Decimal(str(c_data.get('edited_quantity'))))
            except (TypeError, ValueError):
                cantidad = Decimal('0.00')
        else:
            try:
                cantidad = abs(Decimal(str(
                    c_data.get('quantity_changed', 0.0) or 0.0)))
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

        producto = db.session.get(Product, p_id)
        fila_prod = por_producto.setdefault(p_id, {
            'product_id': p_id,
            'product_name': (producto.name if producto is not None
                             else 'Insumo #{0}'.format(p_id)),
            'quantity': Decimal('0.00'),
            'buckets': dict(vacio),
        })
        fila_prod['quantity'] += cantidad
        if moneda not in fila_prod['buckets']:
            fila_prod['buckets'][moneda] = Decimal('0.00')
        fila_prod['buckets'][moneda] += monto

    for clave in ('USD', 'BS', 'EUR'):
        total[clave] = total[clave].quantize(Decimal('0.01'))
    for sede in por_sede:
        for clave in ('USD', 'BS', 'EUR'):
            por_sede[sede][clave] = por_sede[sede][clave].quantize(Decimal('0.01'))
    lista_productos = list(por_producto.values())
    for fila in lista_productos:
        fila['quantity'] = fila['quantity'].quantize(Decimal('0.01'))
        for clave in fila['buckets']:
            fila['buckets'][clave] = fila['buckets'][clave].quantize(
                Decimal('0.01'))
    return {'total': total, 'por_sede': por_sede,
            'por_producto': lista_productos}


def _total_real_compra(compra):
    """Importe realmente pagado en la moneda de la compra.

    La cabecera (Purchase.total_amount) guarda el total exacto de la factura.
    NO se reconstruye con cantidad × precio unitario: el detalle solo conserva
    dos decimales por unidad (p. ej. 100,00 / 160 = 0,625 → 0,63), y volver a
    multiplicar arrastra una desviación de 0,80 EUR en esa factura."""
    total = Decimal(str(compra.total_amount or 0))
    if total:
        return total
    # Respaldo solo para registros antiguos sin total de cabecera.
    total = Decimal('0.00')
    moneda = (compra.currency or 'USD').upper()
    for detalle in compra.details:
        cantidad = Decimal(str(detalle.quantity or 0))
        if moneda in ('BS', 'VES', 'BS.', 'BSS'):
            total += cantidad * Decimal(str(detalle.price_bs or 0))
        else:
            total += cantidad * Decimal(str(detalle.foreign_price or 0))
    return total


def _total_bs_compra(compra, moneda, total_real):
    """Bolívares realmente registrados por la compra.

    En compras en Bs el total de cabecera ya está en bolívares. En compras en
    divisa se usa la tasa guardada ese día (Bs por unidad de la divisa), no la
    suma de price_bs de cada línea: price_bs también nace del precio unitario
    redondeado y reproduce la misma desviación (101.715,20 vs 100.907,17)."""
    if moneda in ('BS', 'VES', 'BS.', 'BSS'):
        return total_real
    tasa = Decimal(str(compra.exchange_rate or 0))
    if tasa:
        return (total_real * tasa).quantize(Decimal('0.01'),
                                            rounding=ROUND_HALF_UP)
    total = Decimal('0.00')
    for detalle in compra.details:
        total += (Decimal(str(detalle.quantity or 0))
                  * Decimal(str(detalle.price_bs or 0)))
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def obtener_compras_consolidado(desde, hasta):
    """Líneas REALES de compras del rango (importe pagado, categoría contable y
    moneda original). 'buckets' contiene SOLO la moneda nativa de pago;
    'buckets_equivalentes' conserva la valoración contable en las tres monedas
    (incluido el Bs registrado con la tasa del día). El importe de cada compra
    sale de la cabecera (total_amount) y se reparte entre categorías según el
    peso de cada línea, para no reintroducir el redondeo unitario. El gasto por
    compra pertenece a la sede Central."""
    linea_vacia = {
        'buckets': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'), 'EUR': Decimal('0.00')},
        'buckets_equivalentes': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
                                 'EUR': Decimal('0.00')},
        'equivalente': {'USD': Decimal('0.00'), 'BS': Decimal('0.00'),
                        'EUR': Decimal('0.00')},
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
        total_real = _total_real_compra(compra)
        total_bs_real = _total_bs_compra(compra, moneda_orig, total_real)
        if moneda_orig in ('BS', 'VES', 'BS.', 'BSS'):
            bucket = 'BS'
        elif moneda_orig == 'EUR':
            bucket = 'EUR'
        else:
            bucket = 'USD'

        lineas = []
        for detalle in compra.details:
            producto = db.session.get(Product, detalle.product_id)
            categoria = 'Sin categoría'
            if producto is not None and producto.product_type is not None:
                macro = producto.product_type.category
                categoria = macro.name if macro is not None else 'Sin categoría'
            cantidad = Decimal(str(detalle.quantity or 0))
            if bucket == 'BS':
                monto = cantidad * Decimal(str(detalle.price_bs or 0))
            else:
                monto = cantidad * Decimal(str(detalle.foreign_price or 0))
            lineas.append({'clave': (mes, categoria), 'monto': monto})
        if not lineas:
            continue

        # El total real de la cabecera se reparte entre las categorías según el
        # peso de cada línea. El último tramo absorbe el residuo de redondeo
        # para que la suma de las filas coincida EXACTA con la factura.
        suma_lineas = sum((linea['monto'] for linea in lineas), Decimal('0.00'))
        acum_nativa = Decimal('0.00')
        acum_bs = Decimal('0.00')
        for indice, linea in enumerate(lineas):
            clave = linea['clave']
            if clave not in agrupadas:
                agrupadas[clave] = {
                    'month': mes, 'category': clave[1],
                    'buckets': dict(linea_vacia['buckets']),
                    'buckets_equivalentes': dict(
                        linea_vacia['buckets_equivalentes']),
                    'equivalente': dict(linea_vacia['equivalente']),
                }
            if suma_lineas:
                proporcion = linea['monto'] / suma_lineas
                if indice == len(lineas) - 1:
                    parte = total_real - acum_nativa
                    parte_bs = total_bs_real - acum_bs
                else:
                    parte = (total_real * proporcion).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP)
                    parte_bs = (total_bs_real * proporcion).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                # Líneas sin valorizar: todo el importe a la primera categoría.
                parte = total_real if indice == 0 else Decimal('0.00')
                parte_bs = total_bs_real if indice == 0 else Decimal('0.00')
            acum_nativa += parte
            acum_bs += parte_bs

            # Moneda NATIVA: solo la divisa en que se pagó la compra.
            agrupadas[clave]['buckets'][bucket] += parte

            # Equivalente contable en las tres monedas. El Bs sale de la tasa
            # del día de la compra (total_amount × exchange_rate), no de sumar
            # price_bs unitarios ya redondeados.
            agrupadas[clave]['buckets_equivalentes'][bucket] += parte
            if bucket != 'BS':
                agrupadas[clave]['buckets_equivalentes']['BS'] += parte_bs

            # Equivalente en las TRES monedas con la tasa del día de la compra
            # (la misma base del KPI de compras). Reconversiones con la tasa de
            # cierre inflaban las compras en divisa (110,71 en vez de 109,95).
            fila = agrupadas[clave]
            fila['equivalente'][bucket] += parte
            if bucket != 'BS':
                fila['equivalente']['BS'] += parte_bs
            if bucket == 'USD':
                tasa_eur = obtener_tasa_historica('EUR', compra.purchase_date)
                if tasa_eur:
                    fila['equivalente']['EUR'] += parte_bs / tasa_eur
            elif bucket == 'EUR':
                tasa_usd = obtener_tasa_historica('USD', compra.purchase_date)
                if tasa_usd:
                    fila['equivalente']['USD'] += parte_bs / tasa_usd
            else:
                tasa_usd = (Decimal(str(compra.exchange_rate or 0))
                            or obtener_tasa_historica('USD',
                                                      compra.purchase_date))
                tasa_eur = obtener_tasa_historica('EUR', compra.purchase_date)
                if tasa_usd:
                    fila['equivalente']['USD'] += parte / tasa_usd
                if tasa_eur:
                    fila['equivalente']['EUR'] += parte / tasa_eur

    for fila in agrupadas.values():
        for clave in ('USD', 'BS', 'EUR'):
            fila['buckets'][clave] = fila['buckets'][clave].quantize(
                Decimal('0.01'))
            fila['buckets_equivalentes'][clave] = (
                fila['buckets_equivalentes'][clave].quantize(Decimal('0.01')))
            fila['equivalente'][clave] = fila['equivalente'][clave].quantize(
                Decimal('0.01'))
    return list(agrupadas.values())


def obtener_compras_por_moneda(desde, hasta):
    """Una fila por compra completada del rango con su moneda, la tasa del día
    que el sistema guardó al registrarla (Purchase.exchange_rate; si no está
    guardada se usa la última tasa BCV del día de la compra) y los totales en
    su moneda NATIVA tomados de la cabecera (Purchase.total_amount). El Bs sale
    de total_amount × exchange_rate, no de sumar price_bs unitarios ya
    redondeados, para que la factura y el reporte coincidan al céntimo."""
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
            # La tasa BCV se archiva como 'BS' aunque la compra diga 'VES'.
            tasa = obtener_tasa_historica(moneda, compra.purchase_date) or Decimal('0.00')
        total_real = _total_real_compra(compra)
        total_usd = total_bs = total_eur = Decimal('0.00')
        total_bs = _total_bs_compra(compra, moneda, total_real)
        if moneda == 'EUR':
            total_eur = total_real
        elif moneda not in ('BS', 'VES', 'BS.', 'BSS'):
            total_usd = total_real
        filas.append({
            'currency': moneda,
            'purchase_date': compra.purchase_date,
            'exchange_rate': tasa,
            'total_usd': total_usd.quantize(Decimal('0.01')),
            'total_bs': total_bs.quantize(Decimal('0.01')),
            'total_eur': total_eur.quantize(Decimal('0.01')),
        })
    return filas