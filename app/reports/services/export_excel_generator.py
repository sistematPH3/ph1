from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.reports.services.export_service import formatear_monto

AZUL = '1F3864'
ROJO = 'C8102E'
GRIS = 'D9E2F3'
BORDE_NINGUNO = None


def generar_excel(datos):
    libro = Workbook()

    hoja = libro.active
    hoja.title = 'Reporte'

    _cabecera(hoja, datos['header'])
    _kpis(hoja, datos['kpis'])
    _fila_vacia(hoja)
    _comparativo(hoja, datos['kpis'])

    for titulo, columnas, filas in datos['detalle_tablas']:
        _tabla(hoja, titulo, columnas, filas)

    _fila_vacia(hoja)
    _pie(hoja, datos['header'])

    libro.active.title = 'Reporte'
    buffer = BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return buffer


def _fila_vacia(hoja):
    hoja.append([])


def _cabecera(hoja, header):
    hoja['A1'] = 'Sistema PH'
    hoja['A1'].font = Font(bold=True, size=14, color=ROJO)
    hoja['A2'] = header['titulo']
    hoja['A2'].font = Font(bold=True, size=11, color=AZUL)
    _fila_vacia(hoja)

    renglones = [
        ('Período', header['periodo']),
        ('Rango', header['rango']),
        ('Período anterior', header['periodo_anterior']),
        ('Sede(s)', header['sede']),
        ('Moneda base', header['moneda']),
        ('Generado por', header['generado_por']),
        ('Generado el', header['generado_en']),
    ]
    for etiqueta, valor in renglones:
        hoja.append([etiqueta, valor])
        hoja[hoja.max_row][0].font = Font(bold=True, size=9)
        hoja[hoja.max_row][1].font = Font(size=9)
    for fila_cab in hoja.iter_rows(
            min_row=4, max_row=3 + len(renglones), max_col=2):
        for celda in fila_cab:
            celda.alignment = Alignment(vertical='center', wrap_text=True)
    hoja.column_dimensions['A'].width = 22
    hoja.column_dimensions['B'].width = 60
    _fila_vacia(hoja)


def _tabla_titulo(hoja, titulo):
    hoja.append([titulo])
    celda = hoja[hoja.max_row][0]
    celda.font = Font(bold=True, size=10, color=AZUL)


def _tabla_datos(hoja, columnas, filas, inicio_col=1):
    encabezados = columnas if columnas else ['Detalle']
    renglon = inicio_col
    hoja.append(encabezados)
    fila_enc = hoja.max_row
    for celda in hoja[fila_enc]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=AZUL)
        celda.alignment = Alignment(horizontal='center', vertical='center',
                                    wrap_text=True)
    renglon += 1

    filas_mostrar = filas if filas else [['Sin datos para este período']]
    for fila in filas_mostrar:
        hoja.append(fila)
        fila_actual = hoja.max_row
        for celda in hoja[fila_actual]:
            celda.font = Font(size=9)
            celda.alignment = Alignment(vertical='center', wrap_text=True)

    _anchos(hoja, inicio_col, encabezados, filas_mostrar)
    _fila_vacia(hoja)


def _anchos(hoja, desde, encabezados, filas, minimo=14, maximo=42):
    cantidad = len(encabezados)
    for i in range(desde, desde + cantidad):
        indice = i - desde
        textos = [str(encabezados[indice])]
        for fila in filas:
            if indice < len(fila):
                textos.append(str(fila[indice]))
        ancho = max((len(t) for t in textos), default=minimo)
        # Letra de 9pt: ~1.15 caracteres por unidad; se deja margen.
        hoja.column_dimensions[get_column_letter(i)].width = min(
            maximo, minimo + int(ancho * 1.15))


def _kpis(hoja, kpis):
    _tabla_titulo(hoja, f"KPIs del período ({kpis['moneda']})")
    kpi = kpis['kpis']
    claves = tuple(c for c in ('compras', 'consumo_cocina', 'mermas',
                               'traslados', 'costo_operativo') if c in kpi)
    encabezados = [kpi[c]['label'] for c in claves]
    hoja.append([formatear_monto(kpi[c]['actual']) for c in claves])
    fila = hoja.max_row
    for celda in hoja[fila]:
        celda.font = Font(bold=True, size=10)
        celda.alignment = Alignment(horizontal='center', vertical='center',
                                    wrap_text=True)
    _anchos(hoja, 1, encabezados,
            [[formatear_monto(kpi[c]['actual']) for c in claves]])
    _fila_vacia(hoja)


def _comparativo(hoja, kpis):
    _tabla_titulo(hoja, 'Comparativo con el período anterior')
    kpi = kpis['kpis']
    claves = tuple(c for c in ('compras', 'consumo_cocina', 'mermas',
                               'traslados', 'costo_operativo') if c in kpi)
    _tabla_datos(hoja,
                 ['Métrica', 'Actual', 'Anterior', 'Diferencia', 'Variación %'],
                 [[kpi[c]['label'],
                   formatear_monto(kpi[c]['actual']),
                   formatear_monto(kpi[c]['anterior']),
                   formatear_monto(kpi[c]['diferencia']),
                   (f"{kpi[c]['pct']:.2f}%" if kpi[c]['pct'] is not None
                    else '—')]
                  for c in claves])


def _tabla(hoja, titulo, columnas, filas):
    _tabla_titulo(hoja, titulo)
    _tabla_datos(hoja, columnas, filas)


def _pie(hoja, header):
    hoja.append(['Documento generado por Sistema PH'])
    hoja.append([f"Generado el {header['generado_en']} por "
                 f"{header['generado_por']}"])
    for celda in hoja[hoja.max_row - 1]:
        celda.font = Font(size=8, italic=True, color='808080')
    for celda in hoja[hoja.max_row]:
        celda.font = Font(size=8, italic=True, color='808080')