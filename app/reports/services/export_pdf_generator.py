from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.reports.services.export_service import formatear_monto
from app.reports.services.pdf_cabecera import cabecera_flujo

ANCHO_UTILIZABLE = A4[0] - 30 * mm


def generar_pdf(datos):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=datos['header']['titulo'],
        author=datos['header']['generado_por'],
    )

    estilos = _estilos()
    historia = []

    historia += cabecera_flujo(datos['header'], estilos)
    historia.append(_tabla_metadatos(datos['header'], estilos))
    historia.append(Spacer(1, 6 * mm))

    historia.append(_tabla_kpis(datos['kpis'], estilos))
    historia.append(Spacer(1, 6 * mm))

    historia.append(_tabla_comparativo(datos['kpis'], estilos))
    historia.append(Spacer(1, 6 * mm))

    for titulo, columnas, filas in datos['detalle_tablas']:
        historia.append(Paragraph(titulo, estilos['subtitulo']))
        historia.append(Spacer(1, 2 * mm))
        historia.append(_tabla_generica(columnas, filas, estilos['celda']))
        historia.append(Spacer(1, 5 * mm))

    doc.build(historia, onFirstPage=_pie_pagina, onLaterPages=_pie_pagina)
    buffer.seek(0)
    return buffer


def _estilos():
    base = getSampleStyleSheet()
    return {
        'marca': ParagraphStyle('marca', parent=base['Normal'],
                                fontName='Helvetica-Bold', fontSize=10,
                                textColor=colors.HexColor('#C8102E')),
        'titulo': ParagraphStyle('titulo', parent=base['Title'], fontSize=16,
                                 leading=20),
        'subtitulo': ParagraphStyle('subtitulo', parent=base['Heading2'],
                                    fontSize=12, spaceAfter=6,
                                    textColor=colors.HexColor('#C8102E')),
        'celda': ParagraphStyle('celda', parent=base['Normal'], fontSize=8.5,
                                leading=11),
        'celda_centrada': ParagraphStyle('celda_centrada', parent=base['Normal'],
                                         fontSize=8.5, alignment=TA_CENTER),
        'kpi_valor': ParagraphStyle('kpi_valor', parent=base['Normal'],
                                    fontSize=13, alignment=TA_CENTER,
                                    fontName='Helvetica-Bold'),
        'kpi_nombre': ParagraphStyle('kpi_nombre', parent=base['Normal'],
                                     fontSize=7.5, alignment=TA_CENTER,
                                     textColor=colors.grey),
    }


def _tabla_metadatos(header, estilos):
    filas = [
        ['Período', header['periodo']],
        ['Rango', header['rango']],
        ['Período anterior', header['periodo_anterior']],
        ['Sede(s)', header['sede']],
        ['Moneda base', header['moneda']],
        ['Generado por', header['generado_por']],
        ['Generado el', header['generado_en']],
    ]
    tabla = Table(filas, colWidths=[40 * mm, ANCHO_UTILIZABLE - 40 * mm])
    tabla.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#8A0F1D')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#FBE9EA')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#E8CDCF')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _tabla_kpis(kpis, estilos):
    kpi = kpis['kpis']
    claves = tuple(c for c in ('compras', 'consumo_cocina', 'mermas',
                               'traslados', 'costo_operativo') if c in kpi)
    celdas = [Paragraph('KPIs del período', estilos['subtitulo'])]
    filas = [[Paragraph(kpi[c]['label'], estilos['kpi_nombre'])
              for c in claves]]
    filas.append([Paragraph(formatear_monto(kpi[c]['actual']),
                            estilos['kpi_valor']) for c in claves])
    ancho_celda = ANCHO_UTILIZABLE / len(claves)
    tabla = Table(filas, colWidths=[ancho_celda] * len(claves))
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#C8102E')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#B0B7C3')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#F7F9FC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return tabla


def _tabla_comparativo(kpis, estilos):
    kpi = kpis['kpis']
    claves = tuple(c for c in ('compras', 'consumo_cocina', 'mermas',
                               'traslados', 'costo_operativo') if c in kpi)
    filas = [['Métrica', 'Actual', 'Anterior', 'Diferencia', 'Variación %']]
    for clave in claves:
        item = kpi[clave]
        flecha = '▲' if item['direccion'] == 'up' else (
            '▼' if item['direccion'] == 'down' else '—')
        pct = f"{item['pct']:.2f}%" if item['pct'] is not None else '—'
        filas.append([
            item['label'],
            formatear_monto(item['actual']),
            formatear_monto(item['anterior']),
            f"{flecha} {formatear_monto(item['diferencia'])}",
            pct,
        ])
    tabla = Table(filas, colWidths=[55 * mm, 30 * mm, 30 * mm, 35 * mm,
                                    30 * mm])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#C8102E')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#B0B7C3')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#F7F9FC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _tabla_generica(columnas, filas, estilo_celda):
    if not filas:
        filas = [['Sin datos para este período']]
        columnas = ['']
    celdas = [[Paragraph(str(c), estilo_celda) for c in columnas]]
    for fila in filas:
        celdas.append([Paragraph(str(v), estilo_celda) for v in fila])

    ancho_celda = ANCHO_UTILIZABLE / max(len(columnas), 1)
    tabla = Table(celdas, colWidths=[ancho_celda] * len(columnas))
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#C8102E')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#E8CDCF')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#FFF6F6')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _pie_pagina(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#C8102E'))
    canvas.setLineWidth(0.9)
    canvas.line(15 * mm, 13.5 * mm, A4[0] - 15 * mm, 13.5 * mm)
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 10 * mm, f"Sistema PH — Generado el {_fecha_pie()}")
    canvas.drawRightString(A4[0] - 15 * mm, 10 * mm,
                           f'Página {doc.page}')
    canvas.restoreState()


def _fecha_pie():
    from datetime import datetime
    return datetime.now().strftime('%d/%m/%Y %H:%M')