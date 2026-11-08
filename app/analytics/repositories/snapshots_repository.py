"""Agregadores del cajón de estadísticas (Rápido 1 - Módulo 8).

Cada función devuelve las FILAS en bruto de un hecho económico (compras,
consumo de cocina, mermas o traslados) dentro de un período, ya filtradas por
la regla de negocio correspondiente. La valorización a USD/BS/EUR la hace el
servicio (snapshots_service) usando el motor de costos y las tasas BCV.
"""
import json
import logging
from datetime import datetime, time
from decimal import Decimal

from app.extensions import db
from app.models.logistics_model import Location, Movement, MovementDetail, Purchase, PurchaseDetail
from app.models.waste_model import AuditLog, Waste, WasteDetail
from app.models.statistics_model import StatisticsSnapshot

logger = logging.getLogger(__name__)


def sedes_activas():
    return [loc.id for loc in Location.query.filter_by(is_active=True).all()]


def sede_central():
    """La Sede Central (de orden mínimo) o la primera activa como respaldo."""
    sede = Location.query.filter_by(is_active=True).order_by(Location.id.asc()).first()
    return sede.id if sede else None


def filas_compras(inicio, fin):
    """Detalles de compras en el período (todas pertenecen a la sede central).

    Devuelve [{location_id, product_id, quantity, currency, unit_foreign,
    price_bs, date}] ordenados por fecha.
    """
    loc = sede_central()
    filas = PurchaseDetail.query \
        .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
        .filter(
            Purchase.status.in_(['COMPLETED', 'COMPLETADO']),
            Purchase.purchase_date >= datetime.combine(inicio, time.min),
            Purchase.purchase_date <= datetime.combine(fin, time.max),
        ) \
        .order_by(Purchase.purchase_date.asc()) \
        .all()
    return [
        {
            'location_id': loc,
            'product_id': d.product_id,
            'quantity': Decimal(str(d.quantity or 0)),
            'currency': (p.currency or 'USD').upper(),
            'unit_foreign': Decimal(str(d.foreign_price or 0)),
            'price_bs': Decimal(str(d.price_bs or 0)),
            'date': p.purchase_date,
        }
        for d in filas for p in [d.purchase]
        if (p.currency or 'USD').upper() in ('USD', 'EUR', 'BS')
    ]


def filas_consumo_cocina(inicio, fin):
    """Consumos de cocina (incluye la acción legacy 'CONSUMO_COCINA')."""
    registros = AuditLog.query.filter(
        AuditLog.action.in_(['GASTO_COCINA', 'CONSUMO_COCINA']),
        AuditLog.timestamp >= datetime.combine(inicio, time.min),
        AuditLog.timestamp <= datetime.combine(fin, time.max),
    ).all()
    filas = []
    for log in registros:
        if not log.location_id:
            continue
        data = log.changed_data or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning(
                    "AuditLog ID %s: JSON inválido en changed_data: %s",
                    log.id, exc
                )
                data = {}
        data = data if isinstance(data, dict) else {}
        try:
            cantidad = abs(Decimal(str(data.get('quantity_changed', 0) or 0)))
        except Exception:
            cantidad = Decimal('0.00')
        product_id = data.get('product_id')
        if product_id is None:
            continue
        filas.append({
            'location_id': log.location_id,
            'product_id': int(product_id),
            'quantity': cantidad,
            'date': log.timestamp,
        })
    return filas


def filas_mermas(inicio, fin):
    """Líneas de mermas APROBADO + PENDIENTE + APROBADO_PARCIAL (sin canceladas).

    En una cabecera APROBADO_PARCIAL solo cuentan las líneas con estado
    'APROBADO' (las pendientes aún no impactan el cajón), replicando el criterio
    de register_waste_repository.
    """
    filas = WasteDetail.query \
        .join(Waste, WasteDetail.waste_id == Waste.id) \
        .filter(
            Waste.status.in_(['APROBADO', 'PENDIENTE', 'APROBADO_PARCIAL']),
            Waste.cancelled_at.is_(None),
            Waste.date >= datetime.combine(inicio, time.min),
            Waste.date <= datetime.combine(fin, time.max),
        ) \
        .all()
    return [
        {
            'location_id': d.waste.location_id,
            'product_id': d.product_id,
            'quantity': Decimal(str(d.quantity or 0)),
            'unit_cost_usd': Decimal(str(d.unit_cost or 0)),
            'date': d.waste.date,
        }
        for d in filas
        if d.waste.location_id
        and (d.waste.status != 'APROBADO_PARCIAL' or (d.status or '') == 'APROBADO')
    ]


def filas_traslados(inicio, fin):
    """Movimientos TRASLADO del período, por sede de ORIGEN, sin movimientos
    cancelados/anulados/rechazados (CANCELADO, CANCELADO_EMISOR, ANULADO,
    RECHAZADO): un traslado que nunca salió no es una pérdida.

    Se valoran las PÉRDIDAS (missing_quantity; si es nulo, la cantidad enviada)
    usando el costo del LOTE EXACTO que se envió.
    """
    filas = MovementDetail.query \
        .join(Movement, MovementDetail.movement_id == Movement.id) \
        .filter(
            Movement.type == 'TRASLADO',
            Movement.status.notin_(['CANCELADO', 'CANCELADO_EMISOR', 'ANULADO', 'RECHAZADO']),
            Movement.date >= datetime.combine(inicio, time.min),
            Movement.date <= datetime.combine(fin, time.max),
        ) \
        .all()
    resultado = []
    for d in filas:
        mov = d.movement
        if not mov.origin_location_id:
            continue
        perdida = d.missing_quantity if d.missing_quantity is not None else d.quantity
        if perdida is None:
            continue
        resultado.append({
            'location_id': mov.origin_location_id,
            'product_id': d.product_id,
            'lot_number': d.lot_number,
            'quantity': Decimal(str(perdida)),
            'date': mov.date,
        })
    return resultado


def guardar_snapshots(metric, period_type, inicio, fin, filas_por_sede, user_id=None):
    """UPSERT idempotente de los totales de una métrica por sede y período.

    Además de reescribir las filas presentes, elimina los snapshots del mismo
    (período, métrica, tipo) que quedaron SIN datos (mermas canceladas o
    rechazadas, compras anuladas, traslados resueltos sin pérdida, etc.) para
    que una regeneración refleje siempre el estado real de la base.
    """
    for loc, agg in filas_por_sede.items():
        snap = StatisticsSnapshot.query.filter_by(
            location_id=loc, metric=metric,
            period_type=period_type, period_start=inicio,
        ).first()
        if snap is None:
            snap = StatisticsSnapshot(
                location_id=loc, metric=metric,
                period_type=period_type, period_start=inicio,
            )
            db.session.add(snap)
        snap.period_end = fin
        snap.amount_usd = agg.get('monto_usd', Decimal('0.00'))
        snap.amount_bs = agg.get('monto_bs', Decimal('0.00'))
        snap.amount_eur = agg.get('monto_eur', Decimal('0.00'))
        snap.quantity = agg.get('cantidad', Decimal('0.00'))
        snap.record_count = agg.get('registros', 0)
        if user_id:
            snap.calculated_by_user_id = user_id
    # Solo eliminar obsoletos si HAY datos nuevos para ese período/métrica.
    # Si filas_por_sede está vacía (no hay datos nuevos), NO borrar históricos:
    # pueden ser datos legítimos de meses anteriores que no deben perderse.
    if filas_por_sede:
        obsoletos = StatisticsSnapshot.query.filter(
            StatisticsSnapshot.metric == metric,
            StatisticsSnapshot.period_type == period_type,
            StatisticsSnapshot.period_start == inicio,
            StatisticsSnapshot.location_id.notin_(list(filas_por_sede.keys())),
        )
        for snap in obsoletos.all():
            db.session.delete(snap)
    db.session.flush()