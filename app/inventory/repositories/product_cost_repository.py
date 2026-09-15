"""Consultas para el motor de costos (precios de compra y tasas BCV).

Orden de la regla mixta (decidido con el equipo):
  1) lote exacto -> 2) última compra (por fecha, no por id) -> 3) promedio de las
  últimas 3 compras (suavizador opcional). Todas filtran por purchase_date <=
  as_of para no usar compras posteriores al hecho que se está valorizando.
"""
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.logistics_model import ExchangeRateHistory, Purchase, PurchaseDetail
from app.time_utils import current_ve_time


def tasas_bcv(fecha=None, cache=None):
    """Tasa BCV vigente por moneda para la fecha dada (Bs por unidad).

    Devuelve {currency: Decimal(rate)} con las tasas más recientes cuyo
    timestamp es <= fecha. Si no hay ninguna para una moneda la omite.
    """
    if fecha is None:
        fecha = current_ve_time()
    if cache is not None and fecha in cache:
        return cache[fecha]
    filas = ExchangeRateHistory.query.filter(
        ExchangeRateHistory.timestamp <= fecha
    ).all()
    # Para cada moneda solo cuenta la tasa más reciente (<= fecha).
    mas_reciente = {}
    for r in sorted(filas, key=lambda x: x.timestamp):
        mas_reciente[r.currency] = Decimal(str(r.rate))
    if cache is not None:
        cache[fecha] = mas_reciente
    return mas_reciente


def compra_lote_exacto(product_id, lot_number, as_of=None):
    """Detalle de compra del lote exacto (último por fecha).

    Solo considera compras completadas ('COMPLETED' o el legacy 'COMPLETADO').
    """
    if as_of is None:
        as_of = current_ve_time()
    return PurchaseDetail.query \
        .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
        .filter(
            func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
            PurchaseDetail.product_id == int(product_id),
            PurchaseDetail.lot_number == str(lot_number).strip(),
            Purchase.purchase_date <= as_of,
        ) \
        .order_by(Purchase.purchase_date.desc(), PurchaseDetail.id.desc()) \
        .first()


def compras_producto(product_id, as_of=None, limite=None):
    """Compras completadas del producto (detalle+purchase) ordenadas por fecha DESC.

    Incluye el legacy 'COMPLETADO'. Para cambiar el criterio de completado
    actualizar ambos status aquí y en compra_lote_exacto.
    """
    if as_of is None:
        as_of = current_ve_time()
    q = PurchaseDetail.query \
        .join(Purchase, PurchaseDetail.purchase_id == Purchase.id) \
        .filter(
            func.upper(Purchase.status).in_(['COMPLETED', 'COMPLETADO']),
            PurchaseDetail.product_id == int(product_id),
            Purchase.purchase_date <= as_of,
        ) \
        .order_by(Purchase.purchase_date.desc(), PurchaseDetail.id.desc())
    if limite:
        q = q.limit(limite)
    filas = q.all()
    return [(d, d.purchase) for d in filas]