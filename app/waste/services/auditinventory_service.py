from app.extensions import db
from app.waste.repositories.auditinventory_repository import (
    AuditInventoryRepository,
    NON_INVENTORY_TABLES,
    NON_INVENTORY_ACTIONS,
    NON_INVENTORY_ACTION_PREFIXES,
)
from app.models import Location, Movement, PurchaseAuditLog, Product, WasteDetail
from datetime import datetime, timedelta
from app.time_utils import current_ve_time, TZ_VENEZUELA
from decimal import Decimal
import json
import logging
import re

logger = logging.getLogger(__name__)

_MERMA_REJECT_EVENTS = {'MERMA_RECHAZADA', 'RECHAZADA', 'RECHAZADO', 'MERMA_REJECTED'}
_MERMA_NOVEDADES = {
    'LIMITE': 'supera el límite de merma del producto',
    'TIPO': 'el tipo de merma exige aprobación',
    'TIEMPO': 'supera la frecuencia de mermas esperada de la sede',
    'VENCIDO': 'lote vencido',
}

# Catálogo de novedades oficiales que el operario puede declarar al recibir
# (ver logistics/movement_reception.html). La auditoría muestra el texto
# oficial de la novedad en lugar de reinterpretarla como un faltante.
RECEPTION_NOVELTY_LABELS = {
    'CONFORME': 'Conforme',
    'FALTANTE': 'Faltante de conteo',
    'SOBRANTE': 'Sobrante / excedente',
    'FALTANTE_CONTEO': 'Faltante de conteo',
    'SOBRANTE_EXCEDENTE': 'Sobrante / excedente',
    'PRODUCTO_ERRONEO': 'Producto erróneo / SKU cruzado',
    'INCIDENCIA_TEMPERATURA': 'Ruptura de cadena de frío',
    'VIOLACION_CUSTODIA': 'Violación de custodia / precinto roto',
    'VENCIMIENTO_PROXIMO': 'Alerta de vencimiento próximo',
    'LOTE_NO_COINCIDE': 'Lote no coincide con la guía',
    'RECHAZO_POR_ESPACIO': 'Rechazo parcial por falta de espacio',
    'RETORNO_EMERGENCIA': 'Retorno de emergencia',
    'NOVEDAD_FALTANTE': 'Novedad con faltante',
    'INCIDENCIA_MIXTA': 'Incidencia mixta (múltiples novedades)',
}

# Títulos del banner de la recepción según la causa real registrada. Se arman
# con el sujeto (La recepción / La devolución) para no forzar "llegó
# incompleta" cuando la novedad es espacio, frío, custodia, lote, etc.
RECEPTION_NOVELTY_HEADLINES = {
    'RECHAZO_POR_ESPACIO': '{subject} presentó rechazo por falta de espacio',
    'INCIDENCIA_TEMPERATURA': '{subject} presentó ruptura de cadena de frío',
    'VIOLACION_CUSTODIA': '{subject} presentó violación de custodia / precinto roto',
    'VENCIMIENTO_PROXIMO': '{subject} presentó alerta de vencimiento próximo',
    'LOTE_NO_COINCIDE': '{subject} presentó un lote distinto al de la guía',
    'PRODUCTO_ERRONEO': '{subject} presentó producto erróneo / SKU cruzado',
    'INCIDENCIA_MIXTA': '{subject} presentó múltiples novedades',
    'RETORNO_EMERGENCIA': '{subject} ingresó como retorno de emergencia',
}

# Icono del banner por causa, para que el aviso se identifique de un vistazo.
RECEPTION_NOVELTY_ICONS = {
    'FALTANTE': 'bi-exclamation-triangle-fill',
    'FALTANTE_CONTEO': 'bi-exclamation-triangle-fill',
    'SOBRANTE': 'bi-box-seam-fill',
    'SOBRANTE_EXCEDENTE': 'bi-box-seam-fill',
    'RECHAZO_POR_ESPACIO': 'bi-x-octagon-fill',
    'PRODUCTO_ERRONEO': 'bi-exclamation-octagon-fill',
    'INCIDENCIA_TEMPERATURA': 'bi-thermometer-high',
    'VIOLACION_CUSTODIA': 'bi-shield-exclamation',
    'VENCIMIENTO_PROXIMO': 'bi-calendar-x-fill',
    'LOTE_NO_COINCIDE': 'bi-upc-scan',
    'INCIDENCIA_MIXTA': 'bi-exclamation-diamond-fill',
    'RETORNO_EMERGENCIA': 'bi-arrow-counterclockwise',
}

# Códigos que describen una diferencia de cantidad y no una causa cualitativa.
RECEPTION_QUANTITY_NOVELTIES = {
    'FALTANTE', 'SOBRANTE', 'FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE',
}

# Novedades de NO ADMISIÓN: la mercancía llegó físicamente al muelle pero no
# ingresó por decisión operativa de la sede (p. ej. falta de espacio). La
# porción no recibida es un RECHAZO en sitio, no un faltante del proveedor.
RECEPTION_REJECTION_NOVELTIES = {'RECHAZO_POR_ESPACIO'}

# Códigos agrupadores de logs antiguos: indican "hubo novedad" pero no la
# causa, así que nunca deben ganarle a la novedad real del renglón.
RECEPTION_GENERIC_NOVELTIES = {
    'CALIDAD', 'NOVEDAD', 'INCIDENCIA', 'OTRO', 'OTRA', 'SIN_NOVEDAD',
}

# Alias de los textos que ya vienen legibles desde el formulario de recepción
# (o de payloads históricos) hacia el código oficial del catálogo.
RECEPTION_NOVELTY_ALIASES = {
    'RECHAZO_PARCIAL_POR_FALTA_DE_ESPACIO': 'RECHAZO_POR_ESPACIO',
    'RECHAZO_PARCIAL_POR_ESPACIO': 'RECHAZO_POR_ESPACIO',
    'RECHAZO_POR_FALTA_DE_ESPACIO': 'RECHAZO_POR_ESPACIO',
    'RUPTURA_DE_CADENA_DE_FRIO': 'INCIDENCIA_TEMPERATURA',
    'RUPTURA_CADENA_DE_FRIO': 'INCIDENCIA_TEMPERATURA',
    'TEMPERATURA_FUERA_DE_RANGO': 'INCIDENCIA_TEMPERATURA',
    'ALERTA_DE_VENCIMIENTO_PROXIMO': 'VENCIMIENTO_PROXIMO',
    'VENCIMIENTO_CERCANO': 'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE_CON_LA_GUIA': 'LOTE_NO_COINCIDE',
    'VIOLACION_DE_CUSTODIA': 'VIOLACION_CUSTODIA',
    'VIOLACION_DE_CUSTODIA_PRECINTO_ROTO': 'VIOLACION_CUSTODIA',
    'PRECINTO_ROTO': 'VIOLACION_CUSTODIA',
    'FALTANTE_DE_CONTEO': 'FALTANTE_CONTEO',
    'FALTANTE_FISICO_DE_CONTEO': 'FALTANTE_CONTEO',
    'EXCEDENTE_SOBRANTE_EN_MUELLE': 'SOBRANTE_EXCEDENTE',
    'SOBRANTE_EXCEDENTE_EN_MUELLE': 'SOBRANTE_EXCEDENTE',
    'PRODUCTO_ERRONEO_SKU_CRUZADO': 'PRODUCTO_ERRONEO',
    'SKU_CRUZADO': 'PRODUCTO_ERRONEO',
    'INCIDENCIA_MIXTA_MULTIPLES_NOVEDADES': 'INCIDENCIA_MIXTA',
    'MULTIPLES_NOVEDADES': 'INCIDENCIA_MIXTA',
}


def _canonical_novelty(code):
    """Código oficial de una novedad, normalizando texto libre y alias."""
    key = re.sub(r'[^A-Z0-9]+', '_', str(code or '').upper()).strip('_')
    if not key:
        return ''
    return RECEPTION_NOVELTY_ALIASES.get(key, key)


def _novelty_label(code):
    """Texto legible de una novedad; tolera códigos nuevos sin catálogo."""
    raw = str(code or '').strip()
    canon = _canonical_novelty(raw)
    if not canon or canon == 'CONFORME':
        return RECEPTION_NOVELTY_LABELS['CONFORME']
    if canon in RECEPTION_NOVELTY_LABELS:
        return RECEPTION_NOVELTY_LABELS[canon]
    # Novedad nueva sin catálogo: si ya viene como texto legible se respeta;
    # si viene como código, se muestra sin guiones bajos.
    if ' ' in raw:
        return raw[:1].upper() + raw[1:]
    return raw.replace('_', ' ').capitalize()


def _novelty_headline(subject, novelty, label):
    """Título del banner según la causa real de la novedad."""
    template = RECEPTION_NOVELTY_HEADLINES.get(novelty)
    if template:
        return template.format(subject=subject)
    return f'{subject} presentó una novedad: {label}'


def _novelty_icon(novelty):
    return RECEPTION_NOVELTY_ICONS.get(novelty, 'bi-info-circle-fill')


def _resolve_reception_novelty(general_novelty, item_novelty='', movement_status=''):
    """Elige la novedad que debe encabezar el aviso de recepción.

    Una causa cualitativa real (espacio, frío, vencimiento, lote, custodia,
    producto erróneo) manda sobre la diferencia de cantidad: un rechazo por
    espacio llega incompleto por definición, pero no es un "faltante".
    Los códigos agrupadores (p. ej. "CALIDAD") se descartan para no tapar la
    novedad concreta que trae el renglón.
    """
    codes = []
    for raw in (general_novelty, item_novelty):
        canon = _canonical_novelty(raw)
        if canon and canon != 'CONFORME' and canon not in RECEPTION_GENERIC_NOVELTIES:
            if canon not in codes:
                codes.append(canon)

    if not codes:
        # Respaldo: logs sin novelty_type donde solo quedó el estado del traslado.
        canon = _canonical_novelty(movement_status)
        if canon in RECEPTION_NOVELTY_LABELS and canon != 'CONFORME':
            codes.append(canon)

    if not codes:
        return ''
    qualitative = [
        c for c in codes
        if c not in RECEPTION_QUANTITY_NOVELTIES and c != 'INCIDENCIA_MIXTA'
    ]
    if qualitative:
        return qualitative[0]
    if 'INCIDENCIA_MIXTA' in codes:
        return 'INCIDENCIA_MIXTA'
    return codes[0]

def _novedad_merma(motivos):
    if not isinstance(motivos, dict):
        return ''
    codes = []
    for v in motivos.values():
        if isinstance(v, list):
            codes.extend(str(x).upper() for x in v)
        elif isinstance(v, str):
            codes.append(v.upper())
    textos = [_MERMA_NOVEDADES.get(c, c.lower()) for c in codes]
    return ' · '.join(dict.fromkeys(textos))

def get_audit_view_data(user_id):
    user = AuditInventoryRepository.get_user_by_id(user_id)
    if not user:
        return [], False, None

    is_admin = (user.role_id == 1)
    
    if is_admin:
        locations = AuditInventoryRepository.get_all_locations()
    else:
        allowed_ids = AuditInventoryRepository.get_user_allowed_locations(user_id)
        locations = [loc for loc in AuditInventoryRepository.get_all_locations() if loc.id in allowed_ids]

    return locations, is_admin, user

def fetch_filtered_audit_logs(user, is_admin, filters):
    allowed_locations = None
    
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return [] 

    location_id_filter = filters.get('location_id')
    severity_filter = filters.get('severity')

    if location_id_filter:
        location_id_filter = int(location_id_filter)

    severity_filter = severity_filter.upper() if severity_filter else None

    if not is_admin and location_id_filter:
        if location_id_filter not in allowed_locations:
            return []

    raw_logs = AuditInventoryRepository.get_audit_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        severity_filter=severity_filter
    )
    
    annulled_target_ids = set()
    sorted_logs = sorted(raw_logs, key=lambda x: x.id) 
    
    for log in sorted_logs:
        act_upper = (log.action or '').upper()
        c_data = log.changed_data or {}
        if isinstance(c_data, str):
            try: 
                c_data = json.loads(c_data)
            except json.JSONDecodeError: 
                c_data = {}
        
        notes = c_data.get('notes', '')
        match = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
        
        if match:
            target_id = int(match.group(1))
            if 'REVERSION' in act_upper:
                annulled_target_ids.add(target_id)
            elif 'ACTIVACION' in act_upper or 'REACTIVACION' in act_upper:
                annulled_target_ids.discard(target_id)

    formatted_logs = []
    for log in raw_logs:
        if _is_non_inventory_log(log):
            continue
        changed_data = log.changed_data or {}
        if isinstance(changed_data, str):
            try:
                changed_data = json.loads(changed_data)
            except json.JSONDecodeError:
                changed_data = {}
        
        qty_changed = float(changed_data.get('quantity_changed', 0))
        
        def safe_float(val):
            if val in (None, ''):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        prev_qty = safe_float(changed_data.get('previous_quantity'))
        new_qty = safe_float(changed_data.get('new_quantity'))

        if qty_changed != 0:
            if qty_changed < 0:
                if prev_qty in (0, 0.0, None):
                    if new_qty is not None and new_qty > 0:
                        prev_qty = new_qty - qty_changed
                    else:
                        prev_qty = abs(qty_changed)
                        new_qty = 0.0
                elif new_qty is None:
                    new_qty = prev_qty + qty_changed

            elif qty_changed > 0:
                if prev_qty in (0, 0.0, None) and new_qty in (0, 0.0, None):
                    prev_qty = 0.0
                    new_qty = qty_changed
                elif new_qty is None and prev_qty is not None:
                    new_qty = prev_qty + qty_changed
                elif prev_qty is None and new_qty is not None:
                    prev_qty = new_qty - qty_changed

        if prev_qty is None: prev_qty = 0.0
        if new_qty is None: new_qty = 0.0

        if prev_qty < 0: prev_qty = 0.0
        if new_qty < 0: new_qty = 0.0

        act_upper = (log.action or '').upper()
        is_adjustment_type = any(kw in act_upper for kw in ['REVERSION', 'AJUSTE', 'ACTIVACION'])
        is_annulled = (log.id in annulled_target_ids)

        formatted_logs.append({
            'id': log.id,
            'action': log.action,
            'severity': log.severity,
            'user_name': log.user_name,
            'location_name': log.location_name or changed_data.get('location_name', 'Almacén Principal'),
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else 'N/A',
            'product_name': changed_data.get('product_name') or changed_data.get('producto') or changed_data.get('nombre') or 'N/A',
            'previous_quantity': prev_qty,
            'new_quantity': new_qty,
            'quantity_changed': qty_changed,
            'notes': changed_data.get('notes', ''),
            'is_annulled': is_annulled,
            'is_adjustment_type': is_adjustment_type
        })
        
    return formatted_logs

def process_inventory_action(log_id, current_user, action_type, new_quantity_requested=None, justification_notes="", lot_number=None):
    original_log_tuple = AuditInventoryRepository.get_audit_log_by_id(log_id)
    if not original_log_tuple:
        return {'success': False, 'message': 'El registro de auditoría solicitado no existe.'}
    
    location_id = original_log_tuple.location_id
    action_name_upper = original_log_tuple.action.upper()

    # Las mermas son un registro contable irrevocable: no se editan, anulan ni reactivan.
    if 'MERMA' in action_name_upper:
        return {'success': False, 'message': 'Operación denegada. Una merma no se puede editar, anular ni activar.'}

    if location_id == 1 or "COMPRA" in action_name_upper or "INGRESO" in action_name_upper:
        return {'success': False, 'message': 'Operación denegada. Las compras o registros en el Almacén General no admiten modificaciones.'}

    is_admin = (current_user.role_id == 1)
    is_finance = (current_user.role_id == 6)

    if is_finance:
        return {'success': False, 'message': 'Operación denegada. El perfil de finanzas posee atributos de solo lectura.'}

    log_timestamp = original_log_tuple.timestamp
    if log_timestamp is not None and log_timestamp.tzinfo is None:
        log_timestamp = log_timestamp.replace(tzinfo=TZ_VENEZUELA)
    
    now = datetime.now(TZ_VENEZUELA)
    diff_hours = (now - log_timestamp).total_seconds() / 3600

    if not is_admin:
        if diff_hours > 24:
            return {'success': False, 'message': 'El tiempo límite de 24 horas ha expirado. Solicite la acción al Administrador.'}
    else:
        if diff_hours > (30 * 24):
            return {'success': False, 'message': 'El límite máximo de 30 días permitido para administradores ha expirado.'}

    changed_data = original_log_tuple.changed_data
    if isinstance(changed_data, str):
        try:
            changed_data = json.loads(changed_data)
        except json.JSONDecodeError:
            changed_data = {}
    elif not changed_data:
        changed_data = {}

    product_id = (
        changed_data.get('product_id') or 
        changed_data.get('insumo_id') or 
        changed_data.get('id_producto') or 
        changed_data.get('id_insumo') or 
        changed_data.get('item_id') or 
        changed_data.get('id')
    )
    product_name = changed_data.get('product_name') or changed_data.get('producto') or changed_data.get('nombre') or 'Insumo no especificado'

    if not product_id and product_name != 'Insumo no especificado':
        try:
            from sqlalchemy import text
            res = db.session.execute(text("SELECT id FROM products WHERE LOWER(name) = LOWER(:pname) LIMIT 1"), {'pname': str(product_name).strip()}).fetchone()
            if res:
                product_id = res[0]
            else:
                res_ins = db.session.execute(text("SELECT id FROM insumos WHERE LOWER(nombre) = LOWER(:pname) LIMIT 1"), {'pname': str(product_name).strip()}).fetchone()
                if res_ins:
                    product_id = res_ins[0]
        except Exception as exc:
            logger.warning(
                "No se pudo resolver el producto por nombre '%s': %s",
                product_name, exc,
            )

    if not product_id:
        return {'success': False, 'message': 'El registro carece del identificador de insumo necesario para procesar la acción.'}

    original_qty_changed = Decimal(str(
        changed_data.get('quantity_changed') or 
        changed_data.get('new_quantity') or 
        changed_data.get('cantidad') or 0
    ))
    
    if original_qty_changed == 0:
        p_qty = changed_data.get('previous_quantity')
        n_qty = changed_data.get('new_quantity')
        if p_qty is not None and n_qty is not None:
            original_qty_changed = Decimal(str(n_qty)) - Decimal(str(p_qty))

    current_stock = AuditInventoryRepository.get_current_stock(location_id, product_id)
    current_stock = Decimal('0.00') if current_stock is None else Decimal(str(current_stock))

    new_severity_status = None

    if action_type == 'ANULAR':
        required_adjustment = -original_qty_changed
        final_action = f"REVERSION_{original_log_tuple.action}"
        final_notes = f"Anulación del log #{log_id}. Motivo: {justification_notes}"
        new_severity_status = 'ANULADO'

    elif action_type == 'ACTIVAR':
        required_adjustment = original_qty_changed
        final_action = f"ACTIVACION_{original_log_tuple.action}"
        final_notes = f"Reactivación del log #{log_id}. Motivo: {justification_notes}"
        new_severity_status = 'NORMAL'

    elif action_type == 'EDITAR':
        if new_quantity_requested is None:
            return {'success': False, 'message': 'Debe especificar la nueva cantidad para procesar la edición.'}
        
        new_requested_dec = Decimal(str(new_quantity_requested))
        abs_original = abs(original_qty_changed)

        is_consumption = (
            "GASTO" in action_name_upper or 
            "CONSUMO" in action_name_upper or 
            "MERMA" in action_name_upper or 
            original_qty_changed < 0
        )

        if is_consumption:
            abs_new = abs(new_requested_dec)
            required_adjustment = abs_original - abs_new
        else:
            required_adjustment = new_requested_dec - original_qty_changed

        final_action = f"AJUSTE_{original_log_tuple.action}"
        base_notes = f"Edición del log #{log_id}"
        if is_consumption:
            final_notes = (
                f"{base_notes}: cantidad corregida de {_qty_str(abs_original)} a {_qty_str(abs_new)} unidades."
                f" Motivo: {justification_notes}"
            )
        else:
            final_notes = (
                f"{base_notes}: nueva variación de {_qty_str(original_qty_changed)} a {_qty_str(new_requested_dec)}."
                f" Motivo: {justification_notes}"
            )
        if lot_number:
            final_notes = f"{final_notes}\nLote afectado: {lot_number}"
        new_severity_status = 'EDITADO'
    else:
        return {'success': False, 'message': 'Acción no reconocida.'}

    if required_adjustment < Decimal('0') and current_stock < abs(required_adjustment):
        deficit = abs(required_adjustment) - current_stock
        return {
            'success': False, 
            'message': (
                f"El ajuste excede el stock disponible de {product_name}. "
f"Stock actual: {_qty_str(current_stock)} unidades; este ajuste intenta descontar "
                    f"{_qty_str(abs(required_adjustment))} unidades. Faltan {_qty_str(deficit)} unidades para poder procesarlo."
            )
        }

    new_qty = current_stock + required_adjustment
    severity = "NORMAL"

    try:
        AuditInventoryRepository.register_audit_adjustment(
            user_id=current_user.id,
            location_id=location_id,
            action_type=final_action,
            severity=severity,
            product_id=product_id,
            product_name=product_name,
            prev_qty=float(current_stock),
            new_qty=float(new_qty),
            qty_changed=float(required_adjustment),
            notes=final_notes,
            original_log_id=log_id,
            new_original_severity=new_severity_status,
            lot_number=lot_number
        )
    except Exception as e:
        logger.exception("Error en BD al registrar el movimiento de auditoría de inventario")
        return {'success': False, 'message': 'No se pudo registrar el movimiento. Intenta de nuevo.'}

    return {'success': True, 'message': 'Acción procesada con éxito.'}


# ============================================================================
# VISOR INGRESOS / EGRESOS (diseño tipo movement_audit)
# ============================================================================

MOVEMENT_EVENT_ACTIONS = {
    'DESPACHO_EMISION',
    'CANCELACION_PRE_SALIDA',
    'RECEPCION_CONFORME',
    'RECEPCION_NOVEDAD',
    # Sin esta acción el log caía en el formateador genérico de stock (que busca
    # product_name/quantity_changed) y la auditoría mostraba 'N/A' con 0 → 0.
    'RECEPCION_INCIDENCIA_CALIDAD',
    'RESOLUCION_DISPUTA',
}

SEV_MAP = {
    'NORMAL': ('NORMAL', 'bg-success', 'bi-check-circle-fill'),
    'ALERTA': ('ALERTA', 'ph-badge-warning', 'bi-exclamation-circle-fill'),
    'CRITICO': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'CRITICAL': ('CRÍTICO', 'bg-danger', 'bi-exclamation-triangle-fill'),
    'EDITADO': ('EDITADO', 'bg-warning text-dark', 'bi-pencil-fill'),
    'ANULADO': ('ANULADO', 'bg-danger', 'bi-x-circle-fill'),
    'REABASTECIDO': ('REABASTECIDO', 'bg-info text-white', 'bi-arrow-up-circle-fill'),
}

INCOME_KEYWORDS = ('INGRESO', 'COMPRA', 'RECEPCION', 'REABASTEC', 'ACTIVACION', 'DEVOLUCION', 'ACREDITACION')


def _changed_dict(log):
    c = log.changed_data or {}
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except json.JSONDecodeError:
            c = {}
    return c if isinstance(c, dict) else {}


def _sev_badge(sev):
    sev = (sev or 'NORMAL').upper()
    return SEV_MAP.get(sev, ('NORMAL', 'bg-success', 'bi-check-circle-fill'))


def _fmt_amount(val):
    if val in (None, ''):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _qty_str(value):
    """Texto de cantidad sin decimales de relleno (30 en vez de 30.00)."""
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    if d == d.to_integral_value():
        return str(int(d))
    return ("%f" % float(d)).rstrip("0").rstrip(".")


def _is_non_inventory_log(log):
    """True si el log es de usuarios/seguridad y no debe verse en inventario.

    El repositorio ya filtra en SQL; esto es una salvaguarda adicional para
    payloads antiguos que pudieran llegar sin `affected_table`.
    """
    affected = (getattr(log, 'affected_table', '') or '').lower()
    action = (getattr(log, 'action', '') or '').upper()
    if affected in NON_INVENTORY_TABLES:
        return True
    if action in NON_INVENTORY_ACTIONS:
        return True
    return any(action.startswith(prefix) for prefix in NON_INVENTORY_ACTION_PREFIXES)


_PRODUCT_ID_KEYS = ('product_id', 'insumo_id', 'id_producto', 'id_insumo')


def _item_product_id(item):
    """Id numérico del producto de un ítem/lote, tolerando payloads heterogéneos."""
    for key in _PRODUCT_ID_KEYS:
        val = item.get(key)
        if val in (None, ''):
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _display_product(item, product_names=None):
    """Nombre exacto del producto del ítem/lote; nunca queda vacío.

    Prioriza el nombre que ya trae el payload y, si no viene, lo resuelve con
    el mapa de productos de la base de datos. El último recurso es el id, para
    que un renglón jamás quede sin identificar el alimento.
    """
    name = (
        item.get('product_name') or item.get('nombre_producto')
        or item.get('producto') or item.get('nombre')
    )
    if name:
        return name
    pid = _item_product_id(item)
    if pid is not None:
        resolved = (product_names or {}).get(pid)
        if resolved:
            return resolved
        return f'Insumo #{pid}'
    return 'N/A'


def _entry_seed(row, sede, product, c, is_admin, read_only_role, now):
    sev = (row.severity or 'NORMAL').upper()
    username = getattr(row, 'user_name', None) or 'Sistema'
    ts = row.timestamp
    ts_aware = None
    if ts is not None:
        ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=TZ_VENEZUELA)

    entry = {
        'id': row.id,
        'action': row.action or '',
        'action_label': (row.action or '').replace('_', ' ').title() or '—',
        'sev': sev,
        'sev_label': _sev_badge(sev)[0],
        'sev_class': _sev_badge(sev)[1],
        'sev_icon': _sev_badge(sev)[2],
        'user_name': username,
        # Correo del responsable (trazabilidad); puede venir vacío en logs antiguos.
        'user_email': getattr(row, 'user_email', None) or '',
        'initial': username[0].upper() if username else 'S',
        'ts': ts,
        # Marca de tiempo exacta ya formateada para la vista.
        'ts_display': ts.strftime('%Y-%m-%d %H:%M:%S') if ts else '—',
        'sede': sede,
        'movement_id': c.get('movement_id'),
        'notes': c.get('notes', '') if isinstance(c.get('notes'), str) else '',
        'event_type': 'inventory',
        'can_manage': False,
        'manage_mode': None,
        'timed_out_note': '',
        'is_retorno': False,
        'purchase_id': None,
        'can_view_purchase': False,
    }
    return entry, ts_aware, sev


def _trace_detail(row):
    """Detalle legible sin repetir datos ya visibles en la cabecera de la tarjeta.

    El producto, la sede y el traslado ya se muestran como distintivos arriba;
    aquí solo interesa la observación/motivo del movimiento.
    """
    notes = row.get('notes')
    if isinstance(notes, str) and notes.strip():
        return notes.strip()
    return 'Sin observaciones registradas.'


def _apply_manage(entry, ts_aware, sev, act, is_admin, read_only_role, now):
    """Calcula si un log de inventario operativo admite Editar/Anular/Activar."""
    if entry.get('event_type') != 'inventory':
        return
    if read_only_role:
        return
    if 'MERMA' in act or 'COMPRA' in act or 'INGRESO' in act or 'AJUSTE' in act or 'REVERSION' in act or 'ACTIVACION' in act:
        return
    if sev in ('ANULADO',):
        entry['can_manage'] = True
        entry['manage_mode'] = 'ACTIVAR'
        return
    if sev in ('EDITADO',):
        return

    hours = ((now - ts_aware).total_seconds() / 3600.0) if ts_aware else 0
    if not is_admin and hours > 24:
        entry['timed_out_note'] = 'Tiempo expirado (24h). Solicite corrección al Administrador.'
        return
    if is_admin and hours > 720:
        entry['timed_out_note'] = 'Plazo máximo administrativo expirado (30 días).'
        return

    entry['can_manage'] = True
    entry['manage_mode'] = 'EDITAR_ANULAR'


def _push_inventory_rows(rows, log, c, sev, ts_aware, sede, entry, is_admin, read_only_role, now, annulled_target_ids, product_names=None):
    """Crea las filas de un log operativo de stock (quantity_changed)."""
    qty_changed = _fmt_amount(c.get('quantity_changed', 0)) or 0.0
    prev_qty = _fmt_amount(c.get('previous_quantity'))
    new_qty = _fmt_amount(c.get('new_quantity'))

    if qty_changed != 0:
        if qty_changed < 0:
            if prev_qty in (0, 0.0, None):
                if new_qty is not None and new_qty > 0:
                    prev_qty = new_qty - qty_changed
                else:
                    prev_qty = abs(qty_changed)
                    new_qty = 0.0
            elif new_qty is None:
                new_qty = prev_qty + qty_changed
        else:
            if prev_qty in (0, 0.0, None) and new_qty in (0, 0.0, None):
                prev_qty = 0.0
                new_qty = qty_changed
            elif new_qty is None and prev_qty is not None:
                new_qty = prev_qty + qty_changed
            elif prev_qty is None and new_qty is not None:
                prev_qty = new_qty - qty_changed

    if prev_qty is None:
        prev_qty = 0.0
    if new_qty is None:
        new_qty = 0.0
    prev_qty = max(0.0, prev_qty)
    new_qty = max(0.0, new_qty)

    act = (log.action or '').upper()
    is_adjustment = any(kw in act for kw in ['REVERSION', 'AJUSTE', 'ACTIVACION'])

    row_data = dict(entry)
    row_data.update({
        'event_type': 'inventory',
        'product': _display_product(c, product_names),
        'sku': c.get('sku', 'N/A'),
        'lot': c.get('lot_number', 'N/A'),
        'qty': qty_changed,
        'prev_qty': prev_qty,
        'new_qty': new_qty,
        'is_annulled': log.id in annulled_target_ids,
        'is_adjustment': is_adjustment,
    })
    _apply_manage(row_data, ts_aware, sev, act, is_admin, read_only_role, now)
    rows.append(row_data)


def _push_despacho_rows(rows, log, c, entry, origin_name, destination_name, mov_status, product_names=None):
    items = c.get('items') or []
    if not items:
        return
    total = sum(float(i.get('dispatched_qty', 0)) for i in items)
    for it in items:
        product = _display_product(it, product_names)
        lot = it.get('lot_number') or 'N/A'
        dispatched = float(it.get('dispatched_qty', 0))
        row = dict(entry)
        row.update({
            'event_type': 'despacho',
            'product': product,
            'sku': it.get('sku') or 'N/A',
            'lot': lot,
            'expiration': it.get('expiration_date') or 'N/A',
            'qty': -dispatched,
            'dispatched_qty': dispatched,
            'origin': origin_name,
            'destination': destination_name,
            'movement_status': mov_status,
            # Detalle del renglón para la trazabilidad: producto + lote + cantidad.
            'notes': entry['notes'] or (
                f"Despacho de {_qty_str(dispatched)} de {product} "
                f"(lote {lot}) desde {origin_name} hacia {destination_name}."
            ),
        })
        rows.append(row)


def _push_cancelacion_rows(rows, log, c, entry, origin_name, destination_name, mov_status):
    delta = _fmt_amount((c.get('stock_impact') or {}).get('origin_current_delta')) or 0.0
    reason = c.get('reason', '') or ''
    row = dict(entry)
    row.update({
        'event_type': 'cancelacion',
        'product': f"Mercancía devuelta · Baja de traslado",
        'sku': 'N/A',
        'lot': 'N/A',
        'qty': abs(delta),
        'reason': reason,
        'origin': origin_name,
        'destination': destination_name,
        'movement_status': mov_status,
        'notes': entry['notes'] or (
            f"Cancelación del traslado #{c.get('movement_id')}."
            + (f" Motivo: {reason}" if reason else '')
        ),
    })
    rows.append(row)


def _push_recepcion_rows(rows, log, c, entry, origin_name, destination_name, mov_status, product_names=None):
    items = c.get('items') or []
    notes = entry['notes']
    if not items:
        return
    for it in items:
        product = _display_product(it, product_names)
        lot = it.get('lot_number') or 'N/A'
        dispatched = float(it.get('dispatched_qty') or 0)
        received = float(it.get('received_qty', it.get('dispatched_qty', 0)) or 0)
        missing = float(it.get('missing_qty') or 0)
        if missing <= 0.001 and dispatched - received > 0.001:
            missing = dispatched - received
        # Sobrante: llegó más de lo despachado. No es un faltante y no debe
        # pintarse como "recepción incompleta".
        surplus = max(0.0, received - dispatched)
        raw_novelty = (
            it.get('specific_novelty')
            or it.get('item_condition')
            or it.get('novelty')
            or it.get('novedad')
            or 'CONFORME'
        )
        novelty = _resolve_reception_novelty(
            c.get('novelty_type'), raw_novelty, mov_status
        )
        is_qualitative = bool(novelty) and novelty not in RECEPTION_QUANTITY_NOVELTIES

        # Rechazo en sitio: lo no ingresado se reporta como rechazado, nunca
        # como faltante del proveedor (la mercancía sí llegó al muelle).
        is_rejection = novelty in RECEPTION_REJECTION_NOVELTIES
        rejected = 0.0
        if is_rejection:
            rejected = float(it.get('rejected_qty') or 0)
            if rejected <= 0.001:
                rejected = max(missing, max(0.0, dispatched - received))
            missing = 0.0

        if is_rejection:
            novelty_kind = 'rechazo'
        elif is_qualitative:
            novelty_kind = 'novedad'
        elif surplus > 0.001:
            novelty = 'SOBRANTE'
            novelty_kind = 'sobrante'
        elif missing > 0.001:
            novelty = 'FALTANTE'
            novelty_kind = 'faltante'
        elif novelty:
            # Novedad de cantidad declarada sin diferencia numérica registrada.
            novelty_kind = 'novedad'
        else:
            novelty = 'CONFORME'
            novelty_kind = 'ninguna'

        label = _novelty_label(novelty)
        subject = 'La devolución' if entry.get('is_retorno') else 'La recepción'
        if is_rejection:
            qty_note = f"Rechazado: {_qty_str(rejected)}" if rejected > 0.001 else ''
        elif surplus > 0.001:
            qty_note = f"Sobrante: {_qty_str(surplus)}"
        elif missing > 0.001:
            qty_note = f"Faltante: {_qty_str(missing)}"
        else:
            qty_note = ''

        if novelty_kind == 'rechazo':
            novelty_title = _novelty_headline(subject, novelty, label)
            novelty_summary = ' · '.join(
                x for x in (f'Novedad: {label}', qty_note) if x
            )
            detail = (
                f"Recepción de {product} (lote {lot}) con rechazo en sitio: "
                f"{_qty_str(rejected)} no ingresadas de {_qty_str(dispatched)} "
                f"despachadas ({_qty_str(received)} recibidas)."
            )
        elif novelty_kind == 'faltante':
            novelty_title = f"{subject} llegó incompleta"
            novelty_summary = f"Novedad: {label}" + (f" · {qty_note}" if qty_note else '')
            detail = f"Recepción incompleta de {product} (lote {lot}): faltante de {_qty_str(missing)}."
        elif novelty_kind == 'sobrante':
            novelty_title = f"{subject} llegó con sobrante"
            novelty_summary = f"Novedad: {label}" + (f" · {qty_note}" if qty_note else '')
            detail = f"Recepción con sobrante de {product} (lote {lot}): {_qty_str(surplus)} de más."
        elif novelty_kind == 'novedad':
            # El título refleja la causa real registrada (espacio, frío, lote,
            # custodia, producto erróneo…) en lugar de un genérico de faltante.
            novelty_title = _novelty_headline(subject, novelty, label)
            novelty_summary = ' · '.join(
                x for x in (f'Novedad: {label}', qty_note) if x
            )
            detail = f"Recepción de {product} (lote {lot}) con novedad: {label.lower()}."
            if qty_note:
                detail += f" Diferencia física: {qty_note.lower()}."
        else:
            novelty_title = f"{subject} conforme"
            novelty_summary = ''
            detail = f"Recepción conforme de {product} (lote {lot}): {_qty_str(received)} recibidas."

        row = dict(entry)
        row.update({
            'event_type': 'recepcion',
            'product': product,
            'sku': it.get('sku') or 'N/A',
            'lot': lot,
            'expiration': it.get('expiration_date') or 'N/A',
            'qty': received,
            'dispatched_qty': dispatched,
            'received_qty': received,
            'missing_qty': missing,
            'surplus_qty': surplus,
            'rejected_qty': rejected,
            'novelty': novelty,
            'novelty_label': label,
            'novelty_kind': novelty_kind,
            'novelty_title': novelty_title,
            'novelty_summary': novelty_summary,
            'novelty_icon': _novelty_icon(novelty),
            'notes': notes or detail,
            'origin': origin_name,
            'destination': destination_name,
            'movement_status': mov_status,
            'has_novedad': novelty_kind != 'ninguna',
        })
        rows.append(row)


def _push_resolucion_rows(rows, log, c, entry, origin_name, destination_name, mov_status, product_names=None):
    summary = c.get('resolution_summary') or {}
    # Cada renglón de la resolución lleva el nombre del producto resuelto: la
    # tabla de detalle muestra producto + lote, nunca solo el código del lote.
    items = [
        dict(it, product_name=_display_product(it, product_names))
        for it in (c.get('items') or [])
        if isinstance(it, dict)
    ]
    notes = c.get('general_notes', '') or ''
    credited = _fmt_amount(summary.get('credited_total')) or 0.0
    returned = _fmt_amount(summary.get('returned_total')) or 0.0
    lost = _fmt_amount(summary.get('lost_total')) or 0.0

    if credited > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Acreditación por disputa · Traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': credited,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
            'notes': notes or (
                f"Resolución de la disputa del traslado {c.get('movement_id')}: "
                f"acreditadas {_qty_str(credited)} en destino."
            ),
        })
        rows.append(row)

    if returned > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Devolución a origen por disputa · Traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': returned,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
            'notes': notes or (
                f"Resolución de la disputa del traslado {c.get('movement_id')}: "
                f"devueltas {_qty_str(returned)} al origen."
            ),
        })
        rows.append(row)

    if lost > 0:
        row = dict(entry)
        row.update({
            'event_type': 'resolucion',
            'product': f"Mercancía extraviada · Disputa de traslado {c.get('movement_id')}",
            'sku': 'N/A', 'lot': 'N/A', 'expiration': 'N/A',
            'qty': -lost,
            'origin': origin_name, 'destination': destination_name,
            'movement_status': mov_status,
            'resolution_items': items,
            'resolution_notes': notes,
            'notes': notes or (
                f"Resolución de la disputa del traslado {c.get('movement_id')}: "
                f"{_qty_str(lost)} dadas de baja por extravío."
            ),
        })
        rows.append(row)


def _to_naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _resolve_purchase_id(log, c, ts):
    """Vincula un log INGRESO_COMPRA con su compra usando el historial CREATE."""
    pid = c.get('purchase_id')
    if pid:
        try:
            return int(pid)
        except (TypeError, ValueError):
            return None
    if not ts:
        return None
    for pa in (
        PurchaseAuditLog.query
        .filter(PurchaseAuditLog.action_type == 'CREATE', PurchaseAuditLog.user_id == log.user_id)
        .order_by(PurchaseAuditLog.timestamp.desc())
        .all()
    ):
        if pa.timestamp and ts and abs((_to_naive(pa.timestamp) - (_to_naive(ts) + timedelta(hours=4))).total_seconds()) <= 90:
            return pa.purchase_id
    return None


def get_inventory_audit_entries(filters, user, is_admin):
    """
    Devuelve la lista de eventos de inventario (ingresos y egresos) con los
    traslados repartidos por sede:
      - DESPACHO_EMISION    -> egreso en la sede origen (por ítem/lote)
      - CANCELACION_PRE_SALIDA -> ingreso en la sede origen (mercancía devuelta)
      - RECEPCION_*         -> ingreso en la sede destino (por ítem/lote)
      - RESOLUCION_DISPUTA  -> acreditación/devolución (ingreso) y extravío (egreso)
    """
    allowed_locations = None
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return []

    location_id_filter = filters.get('location_id') or None
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    if not is_admin and location_id_filter and location_id_filter not in allowed_locations:
        location_id_filter = None

    severity_filter = (filters.get('severity') or '').upper() or None

    raw_logs = AuditInventoryRepository.get_audit_logs(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
        severity_filter=severity_filter,
        start_date=filters.get('start_date') or None,
        end_date=filters.get('end_date') or None,
    )

    # --- Detección de anulados/reactivados (mismo criterio que el JS previo) ---
    annulled_target_ids = set()
    for raw in sorted(raw_logs, key=lambda x: x.id):
        c = _changed_dict(raw)
        notes = c.get('notes', '')
        if isinstance(notes, str):
            m = re.search(r'log\s*#\s*(\d+)', notes, re.IGNORECASE)
            if m:
                target_id = int(m.group(1))
                if 'REVERSION' in (raw.action or '').upper():
                    annulled_target_ids.add(target_id)
                elif 'ACTIVACION' in (raw.action or '').upper():
                    annulled_target_ids.discard(target_id)

    # --- Mapa de traslados para resoluciones (location_id NULL) ---
    movement_ids = set()
    for raw in raw_logs:
        c = _changed_dict(raw)
        mid = c.get('movement_id')
        if mid is not None:
            try:
                movement_ids.add(int(mid))
            except (TypeError, ValueError):
                pass

    movement_map = {}
    if movement_ids:
        for mov in Movement.query.filter(Movement.id.in_(movement_ids)).all():
            movement_map[mov.id] = mov

    # --- Mapa de productos de mermas (aprobadas y rechazadas) ---
    # El log de MERMA solo guarda waste_id; el detalle (productos/lotes) vive en waste_details.
    merma_waste_ids = set()
    for raw in raw_logs:
        c = _changed_dict(raw)
        if (raw.action or '').upper() == 'MERMA':
            wid = c.get('waste_id')
            if wid is not None:
                try:
                    merma_waste_ids.add(int(wid))
                except (TypeError, ValueError):
                    pass

    merma_details = {}
    product_ids_all = set()
    if merma_waste_ids:
        for wd in WasteDetail.query.filter(WasteDetail.waste_id.in_(merma_waste_ids)).all():
            merma_details.setdefault(wd.waste_id, []).append({
                'product_id': wd.product_id,
                'qty': float(wd.quantity or 0),
                'lot': wd.lot_number or 'N/A',
            })
            product_ids_all.add(wd.product_id)

    # --- Nombres de producto de TODOS los renglones/lotes de la auditoría ---
    # Despachos, recepciones, resoluciones y logs de stock guardan product_id;
    # se resuelven en bloque para que el nombre del alimento siempre llegue a
    # la plantilla (aunque el payload no traiga product_name).
    def _collect_product_ids(payload):
        ids = set()
        pid = _item_product_id(payload)
        if pid is not None:
            ids.add(pid)
        for key in ('items', 'productos', 'decisiones', 'resolution_items'):
            for it in payload.get(key) or []:
                if isinstance(it, dict):
                    ids |= _collect_product_ids(it)
        return ids

    for raw in raw_logs:
        product_ids_all |= _collect_product_ids(_changed_dict(raw))

    product_map = {}
    if product_ids_all:
        for pr in Product.query.filter(Product.id.in_(product_ids_all)).all():
            product_map[pr.id] = pr.name

    # Nombres de motivos (tipos de merma) para desglosar las líneas de una edición
    merma_type_names = {}
    try:
        from app.models.waste_model import WasteType as _WasteType
        merma_type_names = {
            wt.id: (wt.name or wt.code or f'Tipo {wt.id}')
            for wt in _WasteType.query.all()
        }
    except Exception as exc:
        logger.warning(
            "No se pudieron cargar los nombres de los tipos de merma: %s", exc,
        )
        merma_type_names = {}

    location_cache = {}

    def loc_name(loc_id):
        if not loc_id:
            return '—'
        if loc_id not in location_cache:
            loc = db.session.get(Location, loc_id)
            location_cache[loc_id] = loc.name if loc else f"Sede #{loc_id}"
        return location_cache[loc_id]

    role_id = getattr(user, 'role_id', None)
    read_only_role = role_id in (4, 6)
    can_view_purchase = (
        is_admin
        or bool(getattr(user, 'is_management', False))
        or bool(getattr(user, 'is_manager', False))
        or bool(getattr(user, 'is_finance', False))
    )
    now = datetime.now(TZ_VENEZUELA)

    rows = []
    for log in raw_logs:
        if _is_non_inventory_log(log):
            # Salvaguarda: usuarios/seguridad (p. ej. RECHAZO_SOLICITUD) no son
            # eventos de inventario y no deben caer en el formateador genérico.
            continue
        c = _changed_dict(log)
        act = (log.action or '').upper()
        aff = (getattr(log, 'affected_table', '') or '').lower()
        sev = (log.severity or 'NORMAL').upper()
        sede = getattr(log, 'location_name', None) or c.get('location_name') or 'Almacén Principal'

        is_movement = (
            aff == 'movements'
            and act in MOVEMENT_EVENT_ACTIONS
            and c.get('movement_id') is not None
        )

        entry, ts_aware, sev_upper = _entry_seed(log, sede, None, c, is_admin, read_only_role, now)

        if is_movement:
            mid = int(c['movement_id'])
            mov_obj = movement_map.get(mid)
            origem = mov_obj.origin_location_id if mov_obj else c.get('origin_location_id')
            dest = (mov_obj.destination_location_id if mov_obj else c.get('destination_location_id'))
            if mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA' and not origem:
                origem = mov_obj.destination_location_id
            origin_name = loc_name(origem)
            destination_name = loc_name(dest)
            mov_status = mov_obj.status if mov_obj else None

            entry['movement_id'] = mid
            entry['is_retorno'] = bool(mov_obj and mov_obj.type == 'RETORNO_EMERGENCIA')

            if act == 'DESPACHO_EMISION':
                _push_despacho_rows(
                    rows, log, c, entry, origin_name, destination_name,
                    mov_status, product_map
                )
            elif act == 'CANCELACION_PRE_SALIDA':
                _push_cancelacion_rows(rows, log, c, entry, origin_name, destination_name, mov_status)
            elif act in ('RECEPCION_CONFORME', 'RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD'):
                _push_recepcion_rows(
                    rows, log, c, entry, origin_name, destination_name,
                    mov_status, product_map
                )
            elif act == 'RESOLUCION_DISPUTA':
                _push_resolucion_rows(
                    rows, log, c, entry, origin_name, destination_name,
                    mov_status, product_map
                )
            continue

        # --- Mermas: mostrar TODAS (aprobadas, rechazadas, canceladas, editadas) con su detalle y observación ---
        if act == 'MERMA':
            event = (c.get('event') or '').upper()
            wid = c.get('waste_id')
            try:
                wid = int(wid) if wid is not None else None
            except (TypeError, ValueError):
                wid = None

            detalles = merma_details.get(wid) or []

            # --- Decisión POR PRODUCTO (payload nuevo): una fila por línea decidida.
            #    Cubre MERMA_APROBADA / MERMA_RECHAZADA / MERMA_DECISION (parcial) /
            #    MERMA_PARCIAL (final mixta). Cada producto lleva su propia decisión,
            #    su motivo (si fue rechazado) y su efecto en stock (si fue aprobado).
            decisiones = c.get('decisiones') or []
            if decisiones:
                admin_name = c.get('resolved_by') or c.get('approved_by') or c.get('rejected_by') or 'Administración'
                for dec in decisiones:
                    dia_decision = (dec.get('decision') or '').upper()
                    esR = dia_decision == 'RECHAZADO'
                    pid = dec.get('product_id')
                    try:
                        pid = int(pid) if pid is not None else None
                    except (TypeError, ValueError):
                        pid = None
                    qty = float(dec.get('quantity') or 0)
                    if esR:
                        prev_qty = 0.0
                        new_qty = 0.0
                    else:
                        prev_qty = float(dec.get('stock_antes') or 0)
                        new_qty = float(dec.get('stock_despues') or 0)
                    motivo_linea = str(dec.get('motivo') or '').strip()

                    if esR:
                        texto = (
                            f"Merma RECHAZADA en el producto "
                            f"{dec.get('product_name') or product_map.get(pid, 'N/D')}{(' #' + str(wid)) if wid else ''} "
                            f"por {admin_name}. Sin descuento de stock."
                            + (f" Motivo: {motivo_linea}" if motivo_linea else "")
                        )
                    else:
                        texto = (
                            f"Merma aprobada en el producto "
                            f"{dec.get('product_name') or product_map.get(pid, 'N/D')}{(' #' + str(wid)) if wid else ''} "
                            f"por {admin_name}. Stock: {_qty_str(prev_qty)} → {_qty_str(new_qty)}."
                        )

                    merma_row = dict(entry)
                    merma_row.update({
                        'event_type': 'inventory',
                        'product': dec.get('product_name') or product_map.get(pid, f'Insumo #{pid}' if pid else 'N/A'),
                        'sku': 'N/A',
                        'lot': dec.get('lot') or 'N/A',
                        'qty': -qty,
                        'prev_qty': prev_qty,
                        'new_qty': new_qty,
                        'is_merma': True,
                        'is_merma_rejected': esR,
                        'is_merma_cancelled': False,
                        'is_merma_edited': False,
                        'is_merma_parcial': event in ('MERMA_DECISION', 'MERMA_PARCIAL'),
                        'is_adjustment': False,
                        'is_annulled': False,
                        'can_manage': False,
                        'notes': texto,
                    })
                    rows.append(merma_row)
                continue

            stock_map = {}
            admin_name = 'Administración'
            motivo = ''
            if event == 'MERMA_APROBADA':
                admin_name = c.get('approved_by') or 'Administración'
                # stock real por producto desde descuentos_stock
                for it in c.get('descuentos_stock') or []:
                    pid = it.get('product_id')
                    try:
                        pid = int(pid) if pid is not None else None
                    except (TypeError, ValueError):
                        pid = None
                    if pid is None:
                        continue
                    try:
                        stock_map[pid] = (
                            float(it.get('stock_antes') or 0),
                            float(it.get('stock_despues') or 0),
                            float(it.get('quantity') or 0),
                        )
                    except (TypeError, ValueError):
                        stock_map[pid] = (0.0, 0.0, 0.0)
            elif event == 'MERMA_CANCELADA' or event == 'MERMA_EDITADA':
                admin_name = c.get('cancelled_by') or c.get('edited_by') or 'el autor'
                motivo = c.get('motivo_cancelacion') or c.get('motivo_edicion') or ''
            elif event in _MERMA_REJECT_EVENTS:
                admin_name = c.get('rejected_by') or 'Administración'
                motivo = c.get('motivo_rechazo') or ''
            else:
                admin_name = c.get('resolved_by') or c.get('approved_by') or 'Administración'
                motivo = ''

            # Si no hay detalle en waste_details (dato suplementario), usamos descuentos_stock
            if not detalles:
                detalles = [
                    {'product_id': pid, 'qty': stock_map.get(pid, (0, 0, 0))[2], 'lot': 'N/A'}
                    for pid in stock_map
                ]

            # Cancelación de una merma PENDIENTE: nunca descontó stock.
            # Se muestra UNA fila por log (con el motivo), sin líneas.
            if event == 'MERMA_CANCELADA':
                nombres = [product_map.get(d.get('product_id')) for d in detalles]
                nombres = [n for n in nombres if n]
                producto = ' · '.join(list(dict.fromkeys(nombres))[:2]) or 'Merma'

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': producto,
                    'sku': 'N/A',
                    'lot': 'N/A',
                    'qty': 0.0,
                    'prev_qty': 0.0,
                    'new_qty': 0.0,
                    'is_merma': True,
                    'is_merma_rejected': False,
                    'is_merma_cancelled': True,
                    'is_merma_edited': False,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                    'notes': (
                        f"Cancelación de la merma{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    ),
                })
                rows.append(merma_row)
                continue

            # Edición de una merma PENDIENTE: tampoco descontó stock.
            # Se desglosa línea por línea (producto, lote, motivo y cantidad ANTES → DESPUÉS)
            # a partir del before/after que guardó el propio registro de auditoría.
            if event == 'MERMA_EDITADA':
                ed_by = entry.get('user_name') or c.get('cancelled_by') or c.get('edited_by') or 'el autor'
                motivo = c.get('motivo_cancelacion') or c.get('motivo_edicion') or ''

                before_state = c.get('before') or {}
                after_state = c.get('after') or {}
                before_lines = (before_state.get('lines') or []) if isinstance(before_state, dict) else []
                after_lines = (after_state.get('lines') or []) if isinstance(after_state, dict) else []

                def _st(line):
                    st = line.get('status')
                    return ('' if st is None else str(st) or 'PENDIENTE').upper()

                # Las líneas PENDIENTES se emparejan por orden (la edición las
                # reemplaza en el mismo orden); las ya decididas se conservan iguales.
                before_pending = [b for b in before_lines if isinstance(b, dict) and _st(b) == 'PENDIENTE']
                after_pending = [a for a in after_lines if isinstance(a, dict) and _st(a) == 'PENDIENTE']
                after_decididas = [a for a in after_lines if isinstance(a, dict) and _st(a) != 'PENDIENTE']

                merma_lines = []
                for idx, al in enumerate(after_pending):
                    bl = before_pending[idx] if idx < len(before_pending) else {}
                    try:
                        qty_b = float(bl.get('quantity') or 0)
                    except (TypeError, ValueError):
                        qty_b = 0.0
                    try:
                        qty_a = float(al.get('quantity') or 0)
                    except (TypeError, ValueError):
                        qty_a = 0.0
                    wt_b = bl.get('waste_type_id')
                    wt_a = al.get('waste_type_id')
                    merma_lines.append({
                        'product': product_map.get(al.get('product_id')) or (f'Insumo #{al.get("product_id")}' if al.get('product_id') else 'N/A'),
                        'lot': al.get('lot_number') or 'N/A',
                        'qty_before': qty_b,
                        'qty_after': qty_a,
                        'motivo_before': merma_type_names.get(wt_b, '—') if wt_b else '—',
                        'motivo_after': merma_type_names.get(wt_a, '—') if wt_a else '—',
                        'changed': (qty_b != qty_a) or (wt_b != wt_a),
                    })
                for al in after_decididas:
                    try:
                        qty_a = float(al.get('quantity') or 0)
                    except (TypeError, ValueError):
                        qty_a = 0.0
                    wt_a = al.get('waste_type_id')
                    merma_lines.append({
                        'product': product_map.get(al.get('product_id')) or (f'Insumo #{al.get("product_id")}' if al.get('product_id') else 'N/A'),
                        'lot': al.get('lot_number') or 'N/A',
                        'qty_before': qty_a,
                        'qty_after': qty_a,
                        'motivo_before': merma_type_names.get(wt_a, '—') if wt_a else '—',
                        'motivo_after': merma_type_names.get(wt_a, '—') if wt_a else '—',
                        'changed': False,
                    })

                nombres = [ln['product'] for ln in merma_lines]
                nombres = [n for n in nombres if n]
                producto = ' · '.join(list(dict.fromkeys(nombres))[:2]) or 'Merma'

                cantidad_txt = ''
                antes = c.get('cantidad_antes')
                despues = c.get('cantidad_despues')
                if antes is not None and despues is not None:
                    try:
                        cantidad_txt = f" Cantidad: {_qty_str(antes)} → {_qty_str(despues)}."
                    except (TypeError, ValueError):
                        cantidad_txt = ''

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': producto,
                    'sku': 'N/A',
                    'lot': 'N/A',
                    'qty': 0.0,
                    'prev_qty': 0.0,
                    'new_qty': 0.0,
                    'is_merma': True,
                    'is_merma_rejected': False,
                    'is_merma_cancelled': False,
                    'is_merma_edited': True,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                    'merma_lines': merma_lines,
                    'notes': (
                        f"Edición de la merma{(' #' + str(wid)) if wid else ''} por {ed_by}."
                        f"{cantidad_txt} Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    ),
                })
                rows.append(merma_row)
                continue

            # Creación de una merma PENDIENTE (en espera de aprobación): el stock
            # NO se descuenta aún (solo se reserva), así que no es una merma
            # rechazada. Se muestra una fila informativa por log.
            if event == 'CREADA' and (c.get('status') or '').upper() != 'APROBADO':
                prod_lines = c.get('productos') or []
                nombres = []
                partes = []
                merma_lines = []
                for pl in prod_lines:
                    if not isinstance(pl, dict) or not pl.get('product_id'):
                        continue
                    try:
                        pid = int(pl.get('product_id'))
                    except (TypeError, ValueError):
                        pid = None
                    try:
                        cant = float(pl.get('cantidad') or 0)
                    except (TypeError, ValueError):
                        cant = 0.0
                    wt = pl.get('waste_type_id')
                    try:
                        wt = int(wt) if wt is not None else None
                    except (TypeError, ValueError):
                        wt = None
                    nombre = product_map.get(pid, f'Insumo #{pid}' if pid else 'N/D')
                    nombres.append(nombre)
                    partes.append(f"{nombre} {_qty_str(cant)} en lote {pl.get('lote') or 'N/A'}")
                    merma_lines.append({
                        'product': nombre,
                        'lot': pl.get('lote') or 'N/A',
                        'qty_before': cant,
                        'qty_after': cant,
                        'motivo_before': merma_type_names.get(wt, '—') if wt else '—',
                        'motivo_after': merma_type_names.get(wt, '—') if wt else '—',
                        'changed': False,
                    })
                producto = ' · '.join(list(dict.fromkeys(nombres))[:2]) or 'Merma'
                notas = (f"Merma registrada (en espera de aprobación){(' #' + str(wid)) if wid else ''}. "
                         f"Sin descuento de stock.")
                if partes:
                    notas += " Cantidad: " + '; '.join(partes) + "."
                novedad = _novedad_merma(c.get('motivos'))
                if novedad:
                    notas += " Revisión: " + novedad + "."
                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': producto,
                    'sku': 'N/A',
                    'lot': 'N/A',
                    'qty': 0.0,
                    'prev_qty': 0.0,
                    'new_qty': 0.0,
                    'is_merma': True,
                    'is_merma_rejected': False,
                    'is_merma_pending': True,
                    'is_merma_cancelled': False,
                    'is_merma_edited': False,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                    'merma_lines': merma_lines,
                    'notes': notas,
                })
                rows.append(merma_row)
                continue

            for d in detalles:
                pid = d.get('product_id')
                try:
                    pid = int(pid) if pid is not None else None
                except (TypeError, ValueError):
                    pid = None
                qty_nominal = float(d.get('qty') or 0)
                stock_antes, stock_despues, qty_disc = stock_map.get(pid, (0.0, 0.0, qty_nominal))
                qty = qty_disc if qty_disc else qty_nominal

                merma_row = dict(entry)
                merma_row.update({
                    'event_type': 'inventory',
                    'product': product_map.get(pid, f'Insumo #{pid}' if pid else 'N/A'),
                    'sku': 'N/A',
                    'lot': d.get('lot') or 'N/A',
                    'qty': -qty,
                    'is_merma': True,
                    'is_merma_rejected': event in _MERMA_REJECT_EVENTS,
                    'is_adjustment': False,
                    'is_annulled': False,
                    'can_manage': False,
                })
                if event == 'MERMA_APROBADA':
                    merma_row['prev_qty'] = stock_antes
                    merma_row['new_qty'] = stock_despues
                    merma_row['notes'] = (
                        f"Merma aprobada{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Stock: {_qty_str(stock_antes)} → {_qty_str(stock_despues)}."
                    )
                elif event == 'CREADA':
                    # Merma aprobada automáticamente al registrarla (reglas no
                    # la dejaron pendiente): descontó stock de inmediato.
                    merma_row['prev_qty'] = 0.0
                    merma_row['new_qty'] = 0.0
                    merma_row['notes'] = (
                        f"Merma aprobada automáticamente al registrar{(' #' + str(wid)) if wid else ''}. "
                        f"Descontó {_qty_str(qty)} del stock."
                    )
                else:
                    # Rechazada: sin descuento de stock (prev == new == 0)
                    merma_row['prev_qty'] = 0.0
                    merma_row['new_qty'] = 0.0
                    merma_row['notes'] = (
                        f"Merma RECHAZADA{(' #' + str(wid)) if wid else ''} por {admin_name}. "
                        f"Sin descuento de stock."
                        + (f" Motivo: {motivo}" if motivo else "")
                    )
                rows.append(merma_row)
            continue

        # --- Logs operativos de stock ---
        if 'COMPRA' in act or 'INGRESO' in act:
            entry['purchase_id'] = _resolve_purchase_id(log, c, log.timestamp)
            entry['can_view_purchase'] = can_view_purchase

        _push_inventory_rows(
            rows, log, c, sev, ts_aware, sede, entry,
            is_admin, read_only_role, now, annulled_target_ids, product_map
        )

    # Completa la trazabilidad que consume la plantilla (responsable, fecha y detalle).
    for row in rows:
        if not row.get('ts_display'):
            row['ts_display'] = row['ts'].strftime('%Y-%m-%d %H:%M:%S') if row.get('ts') else '—'
        row['trace_detail'] = _trace_detail(row)

    return rows


def get_filters_date_range(user, is_admin, location_id_filter):
    """Rango (min, max) de fechas con registros para acotar el calendario."""
    if location_id_filter:
        try:
            location_id_filter = int(location_id_filter)
        except (TypeError, ValueError):
            location_id_filter = None

    allowed_locations = None
    if not is_admin:
        allowed_locations = AuditInventoryRepository.get_user_allowed_locations(user.id)
        if not allowed_locations:
            return None, None

    return AuditInventoryRepository.get_audit_logs_date_range(
        allowed_locations=allowed_locations,
        location_id_filter=location_id_filter,
    )