"""Cabecera corporativa compartida por los generadores PDF.

Diseño: logo de la marca a la izquierda; a la derecha, la línea de marca
"PIZZA HUT · SISTEMA PH", el título del documento y una nota institucional,
todo alineado a la derecha y separado del logo por una regla vertical roja.
Debajo, una línea roja horizontal cierra el encabezado.
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROJO = '#C8102E'
TINTO = '#8A0F1D'
GRAFITO = '#1F2328'
GRIS = '#6C757D'

RUTA_LOGO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'static', 'img', 'brand', 'logo_ph.png',
)

ANCHO_UTILIZABLE = A4[0] - 30 * mm
# Aspecto 375x331: alto proporcional al ancho del logo.
ASPECTO = 331 / 375

_marca = ParagraphStyle(
    'ph-marca', fontName='Helvetica-Bold', fontSize=11, leading=13,
    textColor=colors.HexColor(ROJO), alignment=TA_RIGHT,
)
_titulo = ParagraphStyle(
    'ph-titulo', fontName='Helvetica-Bold', fontSize=15, leading=19,
    textColor=colors.HexColor(GRAFITO), alignment=TA_RIGHT,
)
_subtitulo = ParagraphStyle(
    'ph-sub', fontName='Helvetica', fontSize=8.5, leading=11,
    textColor=colors.HexColor(GRIS), alignment=TA_RIGHT,
)


def cabecera_flujo(header, estilos=None):
    """Flowables de cabecera: logo + texto institucional, regla y espaciado.

    `estilos` se conserva por compatibilidad con los generadores; el módulo
    usa sus propios estilos para que todos los PDF se vean idénticos.
    """
    logo = Image(RUTA_LOGO, width=24 * mm, height=24 * mm * ASPECTO)
    logo.hAlign = 'LEFT'

    texto = [
        Paragraph('PIZZA HUT · SISTEMA PH', _marca),
        Paragraph(header['titulo'], _titulo),
        Paragraph('Documento de control interno y auditoría', _subtitulo),
    ]

    tabla = Table(
        [[logo, texto]],
        colWidths=[34 * mm, ANCHO_UTILIZABLE - 34 * mm],
    )
    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (0, 0), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        # Regla vertical roja que separa el logo del bloque de texto.
        ('LINEAFTER', (0, 0), (0, 0), 1.6, colors.HexColor(TINTO)),
        ('RIGHTPADDING', (0, 0), (0, 0), 8 * mm),
    ]))

    return [
        tabla,
        Spacer(1, 3 * mm),
        HRFlowable(width='100%', thickness=1.4,
                   color=colors.HexColor(ROJO)),
        Spacer(1, 4.5 * mm),
    ]