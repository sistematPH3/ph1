"""Motor de costos (Rápido 1 - Módulo 8).

Regla mixta para valorizar inventario:
  1) lote exacto (si el llamador lo indica)
  2) última compra del producto cuya purchase_date <= fecha
  3) promedio ponderado de las últimas 3 compras (metodo='promedio3')

El costo base se calcula en USD y se convierte a la moneda pedida con la tasa
BCV vigente para la fecha del hecho. Los montos se redondean a 2 decimales.

Firmas públicas (contrato con Rápido 2 / Mariuska):
    obtener_costo_unitario(product_id, fecha=None, moneda='USD', metodo='ultima') -> Decimal
    valorizar_cantidad(product_id, cantidad, fecha=None, moneda='USD') -> Decimal
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.inventory.repositories import product_cost_repository as repo

CENTESIMA = Decimal('0.01')


def _redondear(valor, decimales='0.01'):
    return Decimal(str(valor)).quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def _tasas(fecha, cache=None):
    return repo.tasas_bcv(fecha, cache=cache)


def _a_usd(foreign_value, moneda_compra, fecha, tasa_cache=None):
    """Convierte un precio de compra (USD/EUR) a USD usando la tasa BCV.

    purchase.currency solo puede ser USD o EUR. El precio en BS de la compra
    (price_bs) se conserva como está; acá trabajamos con la moneda original.
    `tasa_cache` es un dict compartido (puede estar vacío) donde se guardan
    las tasas consultadas; si es None se consulta sin caché.
    """
    tasas = _tasas(fecha, tasa_cache) if tasa_cache is not None else _tasas(fecha)
    moneda_compra = (moneda_compra or 'USD').upper()
    if moneda_compra == 'USD':
        return _redondear(foreign_value)
    if moneda_compra == 'EUR':
        tasa_usd = tasas.get('USD')
        tasa_eur = tasas.get('EUR')
        if not tasa_usd or not tasa_eur:
            raise ValueError('No hay tasas BCV para convertir EUR a USD.')
        return _redondear(Decimal(str(foreign_value)) * tasa_eur / tasa_usd)
    raise ValueError(f'Moneda de compra no soportada: {moneda_compra}')


def _de_usd_a(monto_usd, moneda, fecha, tasa_cache=None):
    """Convierte el costo en USD a la moneda pedida (tasa BCV de la fecha)."""
    moneda = moneda.upper()
    if moneda == 'USD':
        return _redondear(monto_usd)
    tasas = _tasas(fecha, tasa_cache) if tasa_cache is not None else _tasas(fecha)
    if moneda == 'BS':
        tasa_usd = tasas.get('USD')
        if not tasa_usd:
            raise ValueError('No hay tasa BCV de USD para la fecha.')
        return _redondear(Decimal(str(monto_usd)) * tasa_usd)
    if moneda == 'EUR':
        tasa_usd = tasas.get('USD')
        tasa_eur = tasas.get('EUR')
        if not tasa_usd or not tasa_eur:
            raise ValueError('No hay tasas BCV para convertir a EUR.')
        return _redondear(Decimal(str(monto_usd)) * tasa_eur / tasa_usd)
    raise ValueError(f'Moneda de salida no soportada: {moneda}')


def _promedio_ponderado(filas, fecha, tasa_cache=None):
    """Promedio del costo unitario ponderado por cantidad (últimas 3 compras)."""
    total_qty = Decimal('0')
    total_valor = Decimal('0')
    for detail, purchase in filas:
        qty = Decimal(str(detail.quantity))
        unit_usd = _a_usd(detail.foreign_price, purchase.currency, fecha, tasa_cache)
        total_qty += qty
        total_valor += qty * unit_usd
    if total_qty <= 0:
        return Decimal('0.00')
    return _redondear(total_valor / total_qty)


def _sin_costo():
    return Decimal('0.00')


def obtener_costo_unitario(product_id, fecha=None, moneda='USD', metodo='ultima', lote=None):
    """Costo unitario del producto en la moneda pedida para la fecha dada.

    - metodo='ultima': última compra (regla por defecto).
    - metodo='promedio3': promedio ponderado de las últimas 3 compras.
    - metodo='lote' / lote=<numero>: costo del lote exacto; si ese lote no
      aparece en una compra completada, cae a la última compra (para no
      romper nuestros tickets de merma que validan el lote en inventario).
    Si no hay compras: devuelve 0.00.
    """
    if fecha is None:
        fecha = datetime.utcnow()
    moneda = (moneda or 'USD').upper()
    metodo = (metodo or 'ultima').lower()
    if metodo not in ('ultima', 'promedio3', 'lote'):
        metodo = 'ultima'

    tasa_cache = {}

    if metodo == 'lote' and lote is not None:
        detail = repo.compra_lote_exacto(int(product_id), str(lote).strip(), as_of=fecha)
        if detail is not None:
            unit_usd = _a_usd(detail.foreign_price, detail.purchase.currency, fecha, tasa_cache)
            return _de_usd_a(unit_usd, moneda, fecha, tasa_cache)

    filas = repo.compras_producto(int(product_id), as_of=fecha,
                                  limite=3 if metodo == 'promedio3' else 1)
    if not filas:
        return _sin_costo()

    if metodo == 'promedio3':
        unit_usd = _promedio_ponderado(filas, fecha, tasa_cache)
    else:  # ultima
        detail, purchase = filas[0]
        unit_usd = _a_usd(detail.foreign_price, purchase.currency, fecha, tasa_cache)

    return _de_usd_a(unit_usd, moneda, fecha, tasa_cache)


def valorizar_cantidad(product_id, cantidad, fecha=None, moneda='USD'):
    """Valor total en la moneda pedida para la cantidad dada."""
    unit = obtener_costo_unitario(product_id, fecha=fecha, moneda=moneda)
    return _redondear(unit * Decimal(str(cantidad)))