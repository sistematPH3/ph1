from datetime import datetime
from decimal import Decimal

from app.analytics.services import analysis_reports_service as report_svc
from app.reports.repositories.export_repository import (
    obtener_nombre_autor,
    obtener_nombres_sedes,
)


def formatear_monto(valor):
    """Monto con separador de miles y coma decimal (es-VE)."""
    if valor is None:
        valor = Decimal('0')
    texto = f"{float(valor):,.2f}"
    partes = texto.split('.')
    enteros = partes[0].replace(',', '.')
    return f"{enteros},{partes[1]}"


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
        columnas = ['Proveedor', 'Mes', '# Compras', f'Monto ({moneda})']
        filas = [[fila['supplier_name'], fila['month'], fila['purchase_count'],
                  formatear_monto(fila['monto'])]
                 for fila in detalle.get('por_proveedor', [])]
        tablas.append(('Compras por proveedor', columnas, filas))

    elif metric == 'KITCHEN_CONSUMPTION':
        columnas = ['Registros de consumo de cocina']
        filas = [[detalle.get('registros', 0)]]
        tablas.append(('Consumo de cocina', columnas, filas))

    elif metric == 'WASTE':
        columnas = ['Fecha', 'Sede', 'Tipo de merma', 'Cantidad', 'Costo',
                    'Moneda', 'Costo original']
        filas = [[(fila['date'].strftime('%d/%m/%Y') if fila.get('date')
                   else ''), fila.get('location_name') or fila.get('sede', ''),
                  fila['waste_type'], fila['quantity'],
                  formatear_monto(fila['cost']), fila.get('currency', 'USD'),
                  formatear_monto(fila.get('cost_original', Decimal('0.00'))) + ' '
                  + fila.get('origin_currency', '')]
                 for fila in detalle.get('mermas', [])]
        tablas.append(('Mermas del período (cada registro real)', columnas,
                       filas))

    elif metric == 'TRANSFERS':
        columnas = ['Indicador', 'Valor']
        tiene_enviados = detalle.get('tiene_enviados', True)
        filas = [
            (['Traslados enviados', detalle.get('enviados', 0)]
             if tiene_enviados else
             ['Traslados devueltos', detalle.get('devueltos', 0)]),
            ['Traslados recibidos', detalle.get('recibidos', 0)],
            ['Reposiciones (complementos)', detalle.get('reposiciones', 0)],
            ['Disputas / novedades', detalle.get('disputas', 0)],
            ['Extravíos (cantidad)', detalle.get('extravios_quantity', 0)],
            ['Pérdidas valorizadas ($)', detalle.get('perdidas_valorizadas', Decimal('0.00'))],
        ]
        tablas.append(('Resumen de traslados', columnas, filas))

        recibido = detalle.get('recibido_por_insumo') or {}
        recibido_top = recibido.get('top') or []
        if recibido_top:
            columnas_rec = ['Insumo', 'Cantidad recibida']
            filas_rec = [[f['product_name'], f['quantity']]
                         for f in recibido_top]
            tablas.append(('Mercancía recibida (insumos más trasladados)',
                           columnas_rec, filas_rec))
        recibido_detalle = recibido.get('detalle') or []
        if recibido_detalle:
            columnas_rec = ['Sede', 'Insumo', 'Cantidad', 'Lotes']
            filas_rec = [[f['sede_name'], f['product_name'], f['quantity'],
                          f['lots']] for f in recibido_detalle]
            tablas.append(('Mercancía recibida por sede', columnas_rec,
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
                 direccional[d]['quantity'],
                 formatear_monto(direccional[d]['cost'])]
                for d in dir_orden
            ]
            total = direccional.get('total') or {}
            filas_dir.append(['Total', total.get('conteo', 0),
                              total.get('quantity', Decimal('0.00')),
                              formatear_monto(total.get('cost', Decimal('0.00')))])
            filas_dir.append(['Pérdidas valorizadas', '—', '—',
                              formatear_monto(direccional.get('perdidas', Decimal('0.00')))])
            tablas.append(('Flujo direccional (mercancía y costo)', columnas_dir,
                           filas_dir))

            movimientos = detalle.get('movimientos') or []
            if movimientos:
                columnas_mv = ['Fecha', 'Tipo', 'Estado', 'Origen', 'Destino',
                               'Dirección', 'Mercancía', f'Costo ({moneda})']
                filas_mv = [
                    [m['date'].strftime('%d/%m/%Y'), m['type'], m['status'],
                     m['origin_name'], m['destination_name'], m['direccion'],
                     m['quantity'], formatear_monto(m['cost'])]
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
        filas.append(['Resultado del período',
                      formatear_monto(cons.get('resultado', Decimal('0.00')))])
        tablas.append(('Consolidado financiero (qué y en qué)', columnas,
                       filas))
        columnas_sede = ['Ubicación', f'Monto ({moneda})']
        filas_sede = [
            [fila['sede'], formatear_monto(fila['monto'])]
            for fila in cons.get('por_sede', [])
        ]
        tablas.append(('Consolidado financiero por sede', columnas_sede,
                       filas_sede))
        por_moneda = cons.get('por_moneda') or {}
        columnas_moneda = ['Moneda', 'Gastado (en su moneda)',
                           'Compras', f'Equivalente ({moneda})', '% del total']
        filas_moneda = [
            [fila['currency'], formatear_monto(fila['monto']), fila['compras'],
             formatear_monto(fila['equivalente']),
             formatear_monto(fila.get('pct'))]
            for fila in por_moneda.get('filas', [])
        ]
        tablas.append(('Compras por moneda (en qué moneda se compra más)',
                       columnas_moneda, filas_moneda))

    return tablas