"""Utilidades de parseo numérico para los formularios de inventario.

Los inputs de stock aceptan separadores de miles venezolanos ("1.250,50") y el
formato estándar ("1250.50"). Este módulo normaliza ambos a un literal que
`Decimal` pueda interpretar sin confundir el punto de miles con el decimal.
"""


def normalize_decimal_string(raw):
    """Limpia separadores de miles y unifica el separador decimal a punto.

    Reglas:
      - Si aparecen coma y punto, el último separador es el decimal
        ("1.250,50" -> "1250.50"; "1,250.50" -> "1250.50").
      - Una sola coma con 1 o 2 dígitos finales es separador decimal.
      - Varios puntos: el último grupo de 2 dígitos se conserva como decimal
        ("1.250.000,50" -> "1250000.50").
      - Un único punto se mantiene como separador decimal (formato estándar
        enviado por el navegador).
    """
    text_value = str(raw).strip().replace('\xa0', '').replace(' ', '')
    if not text_value:
        return ''

    if ',' in text_value and '.' in text_value:
        if text_value.rfind(',') > text_value.rfind('.'):
            return text_value.replace('.', '').replace(',', '.')
        return text_value.replace(',', '')

    if ',' in text_value:
        parts = text_value.split(',')
        if len(parts) == 2 and 0 < len(parts[1]) <= 2:
            return parts[0] + '.' + parts[1]
        return text_value.replace(',', '')

    if text_value.count('.') > 1:
        integer_part, _, decimal_part = text_value.rpartition('.')
        if len(decimal_part) == 2 and integer_part:
            return integer_part.replace('.', '') + '.' + decimal_part
        return text_value.replace('.', '')

    return text_value
