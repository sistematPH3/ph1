from datetime import datetime
from decimal import Decimal

from app.analytics.services import analysis_reports_service as report_svc
from app.reports.repositories.export_repository import (
    obtener_nombre_autor,
    obtener_nombres_sedes,
)


def formatear_monto(valor):
    """Monto con separador de miles y coma decimal (es-VE)."""
    return formatear_numero(valor, 2)


def formatear_numero(valor, decimales=2):
    """Número completo es-VE: miles con punto, decimales con coma.

    Ej: 3674.34 -> '3.674,34'; 600000.0 -> '600.000,00'.
    """
    if valor is None or valor == '':
        valor = 0
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{f:,.{decimales}f}"
    partes = texto.split('.')
    enteros = partes[0].replace(',', '.')
    return f"{enteros},{partes[1]}" if len(partes) > 1 else enteros


def formatear_cantidad(valor):
    """Cantidad es-VE sin ceros forzados: '30' o '0,7'."""
    if valor is None:
        return '0'
    f = float(valor)
    decs = 0 if f == int(f) else 2
    return formatear_numero(f, decs)


def formatear_tasa(valor):
    """Tasa de cambio: entera '1' o hasta 4 decimales '846,5131'."""
    if valor is None:
        return '0'
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    decs = 0 if f == int(f) else 4
    return formatear_numero(f, decs)


def construir_exportacion(filtros, user_id):
    """Reúne todo lo que un documento (PDF/Excel) necesita: cabecera de
    auditoría, KPIs, reporte con su comparativo y las tablas de detalle."""
    reporte = report_svc.construir_reporte(filtros, user_id)
    if 'error' in reporte:
        return {'error': reporte['error']}

    sede_ids = reporte['filters']['location_ids']
    incluir_compras = report_svc.aplica_compras(user_id, sede_ids)
    kpis = report_svc.obtener_kpis(sede_ids, filtros.period_type or 'MONTHLY',
                                   filtros.period_start, filtros.moneda or 'USD',
                                   incluir_compras=incluir_compras,
                                   desde=filtros.desde, hasta=filtros.hasta)

    metric = reporte['filters']['metric']
    moneda = reporte['filters']['moneda']
    usuario = obtener_nombre_autor(user_id)

    return {
        'header': {
            'empresa': 'Sistema PH',
            'titulo': f"Reporte de estadística — {_etiqueta_metrica(metric)}",
            'metric': metric,
            'periodo': reporte['period']['label'],
            'rango': (f"{reporte['period']['start']:%d/%m/%Y} al "
                      f"{reporte['period']['end']:%d/%m/%Y}"),
            'periodo_anterior': reporte['period']['previous_label'],
            'sede': obtener_nombres_sedes(sede_ids, filtros.location_id),
            'moneda': moneda,
            'generado_por': usuario,
            'generado_en': datetime.now().strftime('%d/%m/%Y %H:%M'),
        },
        'reporte': reporte,
        'kpis': kpis,
        'detalle_tablas': _tablas_detalle(reporte),
    }


def _etiqueta_metrica(metric):
    etiquetas = {
        'PURCHASES': 'Compras',
        'KITCHEN_CONSUMPTION': 'Gastos de cocina',
        'WASTE': 'Mermas',
        'TRANSFERS': 'Traslados',
        'CONSOLIDATED': 'Consolidado financiero',
    }
    return etiquetas.get(metric, metric)


def _tablas_detalle(reporte):
    metric = reporte['filters']['metric']
    detalle = reporte.get('detail') or {}
    tablas = []

    if metric == 'PURCHASES':
        moneda = reporte['filters']['moneda']
        compras_prov = detalle.get('por_proveedor', [])
        columnas = ['Proveedor', 'Mes', '# Compras', f'Monto ({moneda})']
        filas = [[fila['supplier_name'], fila['month'], fila['purchase_count'],
                  formatear_monto(fila['monto'])]
                 for fila in compras_prov]
        total_compras = sum((_decimal(fila.get('monto')) for fila in compras_prov),
                            Decimal('0.00'))
        total_registros = sum(int(fila.get('purchase_count') or 0)
                             for fila in compras_prov)
        filas.append(['Total', '', total_registros,
                      formatear_monto(total_compras)])
        tablas.append(('Compras por proveedor', columnas, filas))

        # La vista web muestra el desglose contable y por moneda de esas mismas
        # compras; el export debe llevar los mismos bloques y no solo el
        # agregado por proveedor.
        cons_compras = _compras_consolidadas(reporte)
        _agregar_categorias(tablas, cons_compras, moneda)
        _agregar_compras_por_moneda(tablas, cons_compras, moneda)

    elif metric == 'KITCHEN_CONSUMPTION':
        columnas = ['Registros de consumo de cocina']
        filas = [[detalle.get('registros', 0)]]
        tablas.append(('Consumo de cocina', columnas, filas))
        _agregar_top_productos(tablas, detalle.get('top_producto'),
                               'Producto principal / Top productos (cocina)')
        _agregar_costo_por_sede(tablas, detalle.get('por_sede'),
                                reporte['filters']['moneda'],
                                reporte['period']['end'],
                                'Gasto de cocina por sede')

    elif metric == 'WASTE':
        moneda = reporte['filters']['moneda']
        columnas = ['Fecha', 'Sede', 'Tipo de merma', 'Cantidad', 'Costo',
                    'Moneda', 'Costo original']
        filas = [[(fila['date'].strftime('%d/%m/%Y') if fila.get('date')
                   else ''), fila.get('location_name') or fila.get('sede', ''),
                  fila['waste_type'], formatear_cantidad(fila['quantity']),
                  formatear_monto(fila['cost']), fila.get('currency', 'USD'),
                  formatear_monto(fila.get('cost_original', Decimal('0.00'))) + ' '
                  + fila.get('origin_currency', '')]
                 for fila in detalle.get('mermas', [])]
        tablas.append(('Mermas del período (cada registro real)', columnas,
                       filas))

        # Resumen y top de productos: mismo bloque que la tarjeta de la web.
        _agregar_top_productos(tablas, detalle.get('top_producto'),
                               'Producto principal / Top productos (mermas)')
        resumen = _resumen_mermas(detalle.get('mermas', []), moneda)
        if resumen:
            tablas.append(('Resumen de mermas del período',
                           ['Concepto', 'Valor'], resumen))
        _agregar_costo_por_sede(tablas, detalle.get('por_sede'), moneda,
                                reporte['period']['end'],
                                'Mermas por sede')

    elif metric == 'TRANSFERS':
        moneda = reporte['filters']['moneda']
        columnas = ['Indicador', 'Valor']
        tiene_enviados = detalle.get('tiene_enviados', True)
        filas = [
            (['Traslados enviados', detalle.get('enviados', 0)]
             if tiene_enviados else
             ['Traslados devueltos', detalle.get('devueltos', 0)]),
            ['Traslados recibidos', detalle.get('recibidos', 0)],
            ['Reposiciones (complementos)', detalle.get('reposiciones', 0)],
            ['Disputas / novedades', detalle.get('disputas', 0)],
            ['Extravíos (cantidad)',
             formatear_cantidad(detalle.get('extravios_quantity', 0))],
            [f'Pérdidas valorizadas ({moneda})',
             formatear_monto(detalle.get('perdidas_valorizadas',
                                         Decimal('0.00')))],
        ]
        tablas.append(('Resumen de traslados', columnas, filas))

        _agregar_perdidas(tablas, detalle, moneda)
        _agregar_recibido_por_sede(tablas, (detalle.get('direccional') or {}),
                                   moneda)

        recibido = detalle.get('recibido_por_insumo') or {}
        recibido_top = recibido.get('top') or []
        if recibido_top:
            columnas_rec = ['Insumo', 'Cantidad recibida']
            filas_rec = [[f['product_name'], formatear_cantidad(f['quantity'])]
                         for f in recibido_top]
            tablas.append(('Mercancía recibida (insumos más trasladados)',
                           columnas_rec, filas_rec))
        recibido_detalle = recibido.get('detalle') or []
        if recibido_detalle:
            columnas_rec = ['Sede', 'Insumo', 'Cantidad', 'Lotes']
            filas_rec = [[f['sede_name'], f['product_name'],
                          formatear_cantidad(f['quantity']), f['lots']]
                         for f in recibido_detalle]
            tablas.append(('Mercancía recibida por sede e insumo', columnas_rec,
                           filas_rec))

        direccional = detalle.get('direccional') or {}
        if direccional:
            moneda = direccional.get('moneda', 'USD')
            dir_nombres = {'recibidos': 'Recibidos', 'enviados': 'Enviados',
                           'devueltos': 'Devueltos'}
            dir_orden = (['devueltos', 'recibidos']
                         if not tiene_enviados
                         else ['recibidos', 'enviados'])
            columnas_dir = ['Dirección', '# Traslados', 'Mercancía',
                            f'Costo ({moneda})']
            filas_dir = [
                [dir_nombres[d], direccional[d]['conteo'],
                 formatear_cantidad(direccional[d]['quantity']),
                 formatear_monto(direccional[d]['cost'])]
                for d in dir_orden
            ]
            total = direccional.get('total') or {}
            filas_dir.append(['Total', total.get('conteo', 0),
                              formatear_cantidad(total.get('quantity',
                                                           Decimal('0.00'))),
                              formatear_monto(total.get('cost',
                                                        Decimal('0.00')))])
            filas_dir.append([f'Pérdidas valorizadas ({moneda})', '—', '—',
                              formatear_monto(direccional.get('perdidas',
                                                              Decimal('0.00')))])
            tablas.append(('Flujo direccional (mercancía y costo)',
                           columnas_dir, filas_dir))

            movimientos = detalle.get('movimientos') or []
            if movimientos:
                columnas_mv = ['Fecha', 'Tipo', 'Estado', 'Origen', 'Destino',
                               'Dirección', 'Mercancía', f'Costo ({moneda})']
                filas_mv = [
                    [m['date'].strftime('%d/%m/%Y'), m['type'], m['status'],
                     m['origin_name'], m['destination_name'],
                     m['direccion'], formatear_cantidad(m['quantity']),
                     formatear_monto(m['cost'])]
                    for m in movimientos
                ]
                tablas.append(('Movimientos del período', columnas_mv, filas_mv))

    elif metric == 'CONSOLIDATED':
        cons = detalle.get('consolidado') or {}
        moneda = cons.get('moneda', 'USD')
        columnas = ['Concepto', '$ (USD)', 'Bs', 'EUR (€)',
                    f'Monto ({moneda})']
        filas = [
            [fila['concepto'], formatear_monto(fila.get('buckets', {}).get('USD')),
             formatear_monto(fila.get('buckets', {}).get('BS')),
             formatear_monto(fila.get('buckets', {}).get('EUR')),
             formatear_monto(fila['monto'])]
            for fila in cons.get('por_concepto', [])
        ]
        filas.append(['Pérdidas operativas (cocina + mermas y pérdidas)', '', '', '',
                      formatear_monto(cons.get('total_operativo',
                                               Decimal('0.00')))])
        filas.append([cons.get('total_etiqueta',
                               'Inversión real en compras'), '', '', '',
                      formatear_monto(cons.get('total_registrado',
                                               Decimal('0.00')))])
        tablas.append(('Consolidado financiero (qué y en qué)', columnas,
                       filas))
        distribucion = cons.get('distribucion') or []
        if distribucion:
            tablas.append((f'Distribución de la mercancía comprada ({moneda})',
                           ['Destino', 'Monto', '% del total'],
                           [[f['label'], formatear_monto(f['monto']),
                             f"{f['pct']:.2f} %"] for f in distribucion]))
        traslados = cons.get('traslados') or {}
        columnas_traslados = ['Traslados recibidos', 'Cantidad recibida',
                              f'Costo recibido ({moneda})']
        filas_traslados = [[traslados.get('conteo', 0),
                            formatear_cantidad(traslados.get(
                                'quantity', Decimal('0.00'))),
                            formatear_monto(traslados.get('costo',
                                                          Decimal('0.00')))]]
        en_transito = traslados.get('en_transito') or {}
        if en_transito.get('conteo'):
            filas_traslados.append([
                f"En camino (no recibidos): {en_transito['conteo']}",
                formatear_cantidad(en_transito.get('quantity',
                                                   Decimal('0.00'))),
                formatear_monto(en_transito.get('cost', Decimal('0.00')))])
        sin_recepcion = traslados.get('sin_recepcion') or {}
        if sin_recepcion.get('conteo'):
            filas_traslados.append([
                f"Sin recepción registrada: {sin_recepcion['conteo']}",
                formatear_cantidad(sin_recepcion.get('quantity',
                                                     Decimal('0.00'))),
                formatear_monto(sin_recepcion.get('cost', Decimal('0.00')))])
        if en_transito.get('conteo') or sin_recepcion.get('conteo'):
            filas_traslados.append([
                'Nota: pendientes de recibir (no suman al consolidado)', '', ''])
        tablas.append((
            'Traslados del período (informativo, no suma al consolidado)',
            columnas_traslados, filas_traslados))
        filas_recibido = [
            [fila['sede'], fila['conteo'], formatear_cantidad(fila['quantity']),
             formatear_monto(fila['monto'])]
            for fila in (traslados.get('recibido_por_sede') or [])
        ]
        devoluciones = traslados.get('devoluciones') or {}
        filas_recibido.append([
            'Devoluciones al Almacén Central',
            devoluciones.get('conteo', 0),
            formatear_cantidad(devoluciones.get('quantity', Decimal('0.00'))),
            formatear_monto(devoluciones.get('monto', Decimal('0.00'))),
        ])
        tablas.append((
            'Traslados consolidados por sede (los retornos no cuentan como traslado)',
            ['Sede', 'Traslados', 'Cantidad recibida', f'Monto ({moneda})'],
            filas_recibido))
        columnas_sede = ['Sede', 'Mermas', 'Cocina', 'Pérdidas de traslado',
                         f'Total ({moneda})']
        filas_sede = [
            [fila['sede'], formatear_monto(fila.get('mermas')),
             formatear_monto(fila.get('cocina')),
             formatear_monto(fila.get('perdidas')),
             formatear_monto(fila['monto'])]
            for fila in cons.get('por_sede', [])
        ]
        tablas.append(('Gasto operativo por sede (sin compras)', columnas_sede,
                       filas_sede))
        por_moneda = cons.get('por_moneda') or {}
        columnas_moneda = ['Moneda', 'Gastado (en su moneda)',
                           'Compras', f'Equivalente ({moneda})', '% del total']
        filas_moneda = [
            [fila['currency'], formatear_monto(fila['monto']), fila['compras'],
             formatear_monto(fila['equivalente']),
             formatear_monto(fila.get('pct')) + ' %']
            for fila in por_moneda.get('filas', [])
        ]
        tablas.append(('Compras por moneda (en qué moneda se compra más)',
                       columnas_moneda, filas_moneda))

        _agregar_ranking_operativo(tablas, cons, moneda)
        _agregar_devoluciones_por_sede(tablas, cons, moneda)
        # Mismo bloque de pérdidas por producto/lote que la vista consolidada.
        _agregar_perdidas(tablas, detalle, moneda)

    return tablas


def _decimal(valor):
    if valor is None or valor == '':
        return Decimal('0.00')
    return Decimal(str(valor))


def _compras_consolidadas(reporte):
    """Desglose contable de compras con la misma valorización del reporte."""
    return report_svc.consolidado_financiero(
        reporte['filters']['location_ids'],
        reporte['period']['start'], reporte['period']['end'],
        reporte['filters']['moneda'], incluir_compras=True)


def _agregar_categorias(tablas, cons, moneda):
    filas_cat = cons.get('por_categoria') or []
    if not filas_cat:
        return
    filas = [[fila['category'], formatear_monto(fila['monto'])]
             for fila in filas_cat]
    total = sum((_decimal(fila['monto']) for fila in filas_cat),
                Decimal('0.00'))
    filas.append(['Total', formatear_monto(total)])
    tablas.append(('Compras por categoría contable',
                   ['Categoría', f'Monto ({moneda})'], filas))


def _agregar_compras_por_moneda(tablas, cons, moneda):
    por_moneda = cons.get('por_moneda') or {}
    filas_moneda = por_moneda.get('filas') or []
    if not filas_moneda:
        return
    filas = [
        [fila['currency'], formatear_monto(fila['monto']), fila['compras'],
         formatear_monto(fila['equivalente']),
         formatear_monto(fila.get('pct')) + ' %']
        for fila in filas_moneda
    ]
    filas.append(['Total', '', '', formatear_monto(cons.get('total_compras',
                                                            Decimal('0.00'))),
                  '100,00 %'])
    tablas.append(('Compras por moneda (en qué moneda se compra más)',
                   ['Moneda', 'Gastado (en su moneda)', 'Compras',
                    f'Equivalente ({moneda})', '% del total'], filas))


def _agregar_top_productos(tablas, top, titulo):
    filas_top = (top or {}).get('filas') or []
    if not filas_top:
        return
    moneda = (top or {}).get('moneda', '')
    filas = [[fila['product_name'], formatear_cantidad(fila['quantity']),
              formatear_monto(fila.get('pct')) + ' %',
              formatear_monto(fila['monto'])]
             for fila in filas_top]
    total_q = sum((_decimal(fila['quantity']) for fila in filas_top),
                  Decimal('0.00'))
    total_m = sum((_decimal(fila['monto']) for fila in filas_top),
                  Decimal('0.00'))
    filas.append(['Total top', formatear_cantidad(total_q), '100,00 %',
                  formatear_monto(total_m)])
    tablas.append((titulo,
                   ['Producto', 'Cantidad', '% del costo',
                    f'Monto ({moneda})'], filas))


def _resumen_mermas(mermas, moneda):
    if not mermas:
        return []
    total_q = sum((_decimal(fila.get('quantity')) for fila in mermas),
                  Decimal('0.00'))
    total_c = sum((_decimal(fila.get('cost')) for fila in mermas),
                  Decimal('0.00'))
    return [['Registros de merma', len(mermas)],
            ['Cantidad total', formatear_cantidad(total_q)],
            [f'Costo total ({moneda})', formatear_monto(total_c)]]


def _agregar_perdidas(tablas, detalle, moneda):
    perdidas = detalle.get('perdidas_detalle') or []
    if not perdidas:
        return
    filas = []
    total_q = Decimal('0.00')
    total_c = Decimal('0.00')
    for fila in perdidas:
        cantidad = _decimal(fila.get('quantity'))
        costo = _decimal(fila.get('cost'))
        total_q += cantidad
        total_c += costo
        filas.append([
            fila['date'].strftime('%d/%m/%Y') if fila.get('date') else '',
            f"{fila.get('origin_name', '')} → {fila.get('destination_name', '')}",
            fila.get('product_name', ''), fila.get('lot_number') or '—',
            formatear_cantidad(cantidad), formatear_monto(costo),
        ])
    filas.append(['Total perdido', '', '', '',
                  formatear_cantidad(total_q), formatear_monto(total_c)])
    tablas.append(('Traslados perdidos — Detalle de mercancía',
                   ['Fecha', 'Origen → Destino', 'Producto', 'Lote',
                    'Cantidad perdida', f'Costo ({moneda})'], filas))


def _agregar_recibido_por_sede(tablas, direccional, moneda):
    filas_sede = direccional.get('recibido_por_sede') or []
    if not filas_sede:
        return
    filas = [[fila['sede'], fila['conteo'],
              formatear_cantidad(fila['quantity']),
              formatear_monto(fila['monto'])] for fila in filas_sede]
    filas.append(['Total', '', '',
                  formatear_monto(sum((_decimal(f['monto'])
                                       for f in filas_sede),
                                      Decimal('0.00')))])
    tablas.append(('Mercancía recibida por sede',
                   ['Sede', 'Traslados', 'Cantidad recibida',
                    f'Monto ({moneda})'], filas))


def _agregar_costo_por_sede(tablas, por_sede, moneda, fecha, titulo):
    if not por_sede:
        return
    montos = []
    for sede, buckets in por_sede.items():
        convertido = report_svc._convertir_buckets(buckets, moneda, fecha)
        montos.append((sede, _decimal(convertido)))
    montos.sort(key=lambda item: -float(item[1]))
    total = sum((monto for _, monto in montos), Decimal('0.00'))
    filas = []
    for sede, monto in montos:
        pct = (monto / total * 100) if total else Decimal('0.00')
        filas.append([sede, formatear_monto(monto),
                      formatear_monto(pct) + ' %'])
    filas.append(['Total', formatear_monto(total), '100,00 %'])
    tablas.append((titulo, ['Sede', f'Costo ({moneda})', '% del total'],
                   filas))


def _agregar_ranking_operativo(tablas, cons, moneda):
    filas_sede = cons.get('por_sede') or []
    if not filas_sede:
        return
    total = sum((_decimal(fila['monto']) for fila in filas_sede),
                Decimal('0.00'))
    filas = []
    for pos, fila in enumerate(filas_sede, start=1):
        monto = _decimal(fila['monto'])
        pct = (monto / total * 100) if total else Decimal('0.00')
        filas.append([pos, fila['sede'], formatear_monto(monto),
                      formatear_monto(pct) + ' %'])
    filas.append(['', 'Total operativo', formatear_monto(total), '100,00 %'])
    tablas.append(('Ranking operativo por sede (sin compras)',
                   ['#', 'Sede', f'Total ({moneda})', '% del gasto'], filas))


def _agregar_devoluciones_por_sede(tablas, cons, moneda):
    traslados = cons.get('traslados') or {}
    devoluciones = traslados.get('devoluciones') or {}
    filas_dev = devoluciones.get('por_sede') or []
    if not filas_dev:
        return
    filas = [[fila['sede'], fila['conteo'],
              formatear_cantidad(fila['quantity']),
              formatear_monto(fila['monto'])] for fila in filas_dev]
    filas.append(['Total devuelto', devoluciones.get('conteo', 0),
                  formatear_cantidad(devoluciones.get('quantity',
                                                     Decimal('0.00'))),
                  formatear_monto(devoluciones.get('monto',
                                                   Decimal('0.00')))])
    tablas.append(('Devoluciones al Almacén Central por sede',
                   ['Sede', 'Devoluciones', 'Cantidad',
                    f'Monto ({moneda})'], filas))