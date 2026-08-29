# app/logistics/services/movement_dispute_service.py
#
# Servicio del sub-módulo de Arbitraje / Bandeja de Novedades.
# Aquí vive TODA la lógica de negocio de las disputas de traslados:
#   - Enriquecimiento de la bandeja (listado + auditoría de recepción).
#   - Resolución del veredicto granular con las 4 decisiones contables.
#   - Cancelación de reposiciones complementarias.
#
# El archivo de rutas (movement_dispute_routes.py) se limita a recibir HTTP,
# delegar en estas funciones y devolver respuestas.

from datetime import datetime
from decimal import Decimal
import json

from app.extensions import db
from app.models import AuditLog, Inventory, Location, Movement, MovementDetail

# ---------------------------------------------------------------------------
# CATÁLOGO DE DECISIONES CONTABLES
# ---------------------------------------------------------------------------
# REGLA CONTABLE BASE: process_reception NUNCA acredita el inventario de
# destino cuando la recepción registró una novedad (solo acredita recepciones
# CONFORME). Por lo tanto, la porción CONFORME recibida físicamente en la sede
# (min(recibido, autorizado)) se acredita en la resolución según la decisión.

# Tipos de novedad de CALIDAD/CONDICIÓN (no de cantidad): el producto llega
# físicamente COMPLETO a destino, pero en mal estado o con datos que no
# cuadran (temperatura, precinto, lote).
#
# BUGFIX: el código viejo suponía que process_reception "ya había acreditado de
# forma optimista" la cantidad completa al inventario de destino, y todo el
# bloque de RETURN/WRITE_OFF estaba escrito para "revertir" ese supuesto
# crédito. Eso es falso: revisando movement_reception_service.py, process_reception
# SOLO acredita a destino cuando final_status == 'COMPLETADO', y eso nunca
# ocurre si hay una novedad. Nunca hubo nada que revertir -- y el guard
# `if credited_qty > 0` a veces dejaba `return_items_payload` vacío, por lo que
# el traslado de retorno JAMÁS se creaba (no aparecía en Arbitraje).
QUALITATIVE_NOVELTY_TYPES = ('INCIDENCIA_TEMPERATURA', 'VIOLACION_CUSTODIA', 'LOTE_NO_COINCIDE')

# Decisión 1: dar de baja -> el producto desaparece. No se acredita a destino
# (nunca se acreditó, ver nota de arriba) y tampoco se repone en origen.
WRITE_OFF_ACTIONS = ('BAJA_EXTRAVIO_PARCIAL', 'DERIVAR_MERMA_SANITARIA')

# Decisión 3: devolver -> el producto regresa físicamente al origen.
RETURN_ACTIONS = ('RESOLUCION_REINTEGRO', 'RETORNO_EMERGENCIA')

# Decisión 2 ("dejar el producto en destino"): ACEPTAR_RECEPCION,
# RECEPCION_CONFORME_FEFO, CORREGIR_LOTE (se corrige el dato pero el producto
# se queda) e INCIDENCIA_INTERNA. Se acredita la porción conforme.

# Acciones de auditoría de recepción que alimentan la bandeja y la resolución.
RECEPTION_AUDIT_ACTIONS = ('RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD', 'RECEPCION_CONFORME')

# Estados de movimiento que la bandeja considera "disputa pendiente".
DISPUTE_STATUSES = (
    'FALTANTE_CONTEO', 'SOBRANTE_EXCEDENTE', 'PRODUCTO_ERRONEO',
    'VIOLACION_CUSTODIA', 'INCIDENCIA_TEMPERATURA', 'VENCIMIENTO_PROXIMO',
    'LOTE_NO_COINCIDE', 'RECHAZO_POR_ESPACIO', 'RETORNO_EMERGENCIA',
    'NOVEDAD_FALTANTE', 'INCIDENCIA_MIXTA'
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _to_decimal(value):
    """Convierte cualquier valor numérico o None a Decimal de forma segura."""
    if value is None:
        return Decimal('0.00')
    return Decimal(str(value))


def _get_or_create_inventory(location_id, product_id):
    """Obtiene el registro de inventario de una sede/producto o lo crea en ceros."""
    inv = Inventory.query.filter_by(location_id=location_id, product_id=product_id).first()
    if not inv:
        inv = Inventory(
            location_id=location_id, product_id=product_id,
            current_quantity=Decimal('0.00'), transit_quantity=Decimal('0.00'), min_stock=Decimal('20.00')
        )
        db.session.add(inv)
    return inv


def _credit_inventory(inv, qty):
    """Suma qty al current_quantity del registro de inventario (si es > 0)."""
    if inv is None or qty <= Decimal('0.00'):
        return
    inv.current_quantity = _to_decimal(inv.current_quantity) + qty


def _read_changed_data(log):
    """Devuelve changed_data como dict (JSONB o string JSON)."""
    if not getattr(log, 'changed_data', None):
        return {}
    data = log.changed_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return {}
    return data or {}


def _get_reception_audit(movement):
    """Recupera la auditoría de recepción del movimiento.

    Devuelve (notes, erroneous_products, audit_items_map):
      - notes: observaciones reales del muelle.
      - erroneous_products: productos no manifestados / entregados por error.
      - audit_items_map: discrepancias indexadas por product_id (contiene type,
        authorized_qty, physical_received_qty, extra_units, notes).
    """
    audit_logs = AuditLog.query.filter(
        AuditLog.affected_table == 'movements',
        AuditLog.action.in_(RECEPTION_AUDIT_ACTIONS)
    ).order_by(AuditLog.id.desc()).all()

    notes = None
    erroneous_products = []
    audit_items_map = {}
    for log in audit_logs:
        data = _read_changed_data(log)
        if not data.get("movement_id") == movement.id:
            continue
        notes = data.get("notes")
        erroneous_products = data.get("erroneous_products_delivered", [])
        for disc in data.get("discrepancies", []):
            prod_id = disc.get("product_id")
            if prod_id:
                audit_items_map[prod_id] = disc
        break
    return notes, erroneous_products, audit_items_map


# ---------------------------------------------------------------------------
# VISTA: BANDEJA DE NOVEDADES / INCIDENCIAS
# ---------------------------------------------------------------------------

def get_disputes_context():
    """Arma el contexto de la bandeja de disputas + auditoría enriquecida.

    Devuelve (disputes, locations) listos para renderizar.
    """
    disputes = Movement.query.filter(
        Movement.status.in_(DISPUTE_STATUSES)
    ).order_by(Movement.date.desc()).all()

    locations = Location.query.all()

    for mov in disputes:
        notes, erroneous_products, audit_items_map = _get_reception_audit(mov)
        mov.reception_notes = notes
        mov.erroneous_products = erroneous_products

        for detail in mov.details:
            detail_audit = audit_items_map.get(detail.product_id, {})
            detail.item_condition = detail_audit.get("type", "CONFORME")
            detail.specific_novelty = detail_audit.get("notes", "Sin observaciones")
            detail.observed_physical_lot = detail_audit.get("observed_physical_lot")

    return disputes, locations


# ---------------------------------------------------------------------------
# RESOLUCIÓN DEL VEREDICTO GRANULAR
# ---------------------------------------------------------------------------

def resolve_dispute(movement_id, payload, user_id):
    """Procesa el veredicto granular de la disputa y actualiza inventarios.

    REGLA CONTABLE BASE: process_reception NUNCA acredita el inventario de
    destino cuando la recepción registró novedad. Por eso, la porción CONFORME
    recibida físicamente en la sede (min(recibido, autorizado)) se acredita
    AQUÍ según la decisión tomada sobre cada ítem:

      1) Dar de baja (DERIVAR_MERMA_SANITARIA): todo el renglón se descarta;
         no se acredita al destino ni se repone en origen.
      2) Baja por extravío parcial (BAJA_EXTRAVIO_PARCIAL): lo conforme
         recibido se queda en destino; lo faltante/extraviado se da de baja.
      3) Devolver (RETURN_ACTIONS): lo conforme se queda en destino y se crea
         un traslado de retorno (linked_movement) en EN_TRANSITO hacia el
         origen; el inventario que regresa se acredita al recibir ese traslado.
         Para novedades de CALIDAD o RECHAZO/RETORNO total se devuelve TODA la
         cantidad recibida (no se acredita nada en destino).
      4) Dejar/recibir (ACEPTAR_RECEPCION, RESOLUCION_ACREDITAR_DESTINO,
         CORREGIR_LOTE, etc.): se acredita la porción que corresponde en
         destino; el faltante no declarado como baja se reintegra a ORIGEN.

    Eleva excepciones si algo falla (el commit/rollback se maneja aquí).
    """
    movement = Movement.query.get(movement_id)
    if not movement:
        raise ValueError("El traslado especificado no existe.")

    general_notes = payload.get("general_notes", "")
    _, erroneous_products, audit_items_map = _get_reception_audit(movement)

    # Banderas auxiliares para la creación automatizada del traslado de retorno.
    has_returns = False
    return_items_payload = []
    resolution_items = []
    linked_return_movement_id = None

    # 1. Procesar resoluciones para los ítems del manifestado original
    for detail in movement.details:
        action = payload.get(f"item_{detail.id}_action")
        new_lot = payload.get(f"item_{detail.id}_lot")

        disc_data = audit_items_map.get(detail.product_id, {})

        qty_missing = _to_decimal(disc_data.get("missing_qty", getattr(detail, 'missing_quantity', 0)))
        extra_units = _to_decimal(disc_data.get("extra_units", 0))
        novelty_type = disc_data.get("type")

        inv_origin = Inventory.query.filter_by(
            location_id=movement.origin_location_id, product_id=detail.product_id
        ).first()

        # AJUSTE DE TRÁNSITO: process_reception ya restó el received_qty del
        # tránsito original. Aquí solo liberamos lo que haya quedado marcado
        # como missing_qty para no dejar stock atascado.
        if inv_origin and inv_origin.transit_quantity is not None:
            current_transit = _to_decimal(inv_origin.transit_quantity)
            inv_origin.transit_quantity = max(Decimal('0.00'), current_transit - qty_missing)

        received_qty = _to_decimal(detail.received_quantity)
        authorized_qty = _to_decimal(detail.quantity)
        conforming_qty = min(received_qty, authorized_qty)
        inv_dest = _get_or_create_inventory(movement.destination_location_id, detail.product_id)

        credited_qty = Decimal('0.00')
        qty_to_return = Decimal('0.00')

        if action == 'CORREGIR_LOTE':
            # Decisión "dejar": el producto se queda, solo se corrige el lote.
            if new_lot:
                detail.lot_number = new_lot
            credited_qty = conforming_qty
            _credit_inventory(inv_dest, credited_qty)

        elif action == 'RESOLUCION_ACREDITAR_DESTINO':
            # Decisión "quedárselo": se acredita TODO lo recibido físicamente
            # (porción autorizada + excedente físico).
            credited_qty = received_qty
            _credit_inventory(inv_dest, credited_qty)

        elif action == 'BAJA_EXTRAVIO_PARCIAL':
            # Baja por extravío parcial: lo conforme queda en destino; lo
            # faltante/extraviado se da de baja (no se repone a nadie).
            credited_qty = conforming_qty
            _credit_inventory(inv_dest, credited_qty)

        elif action == 'DERIVAR_MERMA_SANITARIA':
            # Merma sanitaria: se descarta TODO lo recibido; no se acredita al
            # destino ni se repone en origen.
            detail.received_quantity = Decimal('0.00')
            credited_qty = Decimal('0.00')

        elif action in RETURN_ACTIONS:
            # Decisión 3: DEVOLVER.
            has_returns = True

            rechazo_total = (
                novelty_type in ('RECHAZO_POR_ESPACIO', 'RETORNO_EMERGENCIA')
                or movement.status in ('RECHAZO_POR_ESPACIO', 'RETORNO_EMERGENCIA')
            )

            if novelty_type in QUALITATIVE_NOVELTY_TYPES or rechazo_total:
                # La carga llegó completa pero NO se queda: o está en mal estado
                # (calidad) o no cupo / fue rechazada por espacio. Se regresa
                # TODO lo recibido; no se acredita nada en destino. BUGFIX vs
                # código viejo que calculaba extra+missing = 0 y no creaba nada.
                qty_to_return = received_qty
                detail.received_quantity = Decimal('0.00')
            else:
                # Reintegro parcial (ej. sobrante): lo conforme se queda
                # acreditado en destino; devuelven el excedente físico
                # (extra_units) y/o el remanente que no se descargó (missing).
                credited_qty = conforming_qty
                _credit_inventory(inv_dest, credited_qty)
                qty_to_return = extra_units + qty_missing

            if qty_to_return > Decimal('0.00'):
                return_items_payload.append({
                    "product_id": detail.product_id,
                    "quantity": qty_to_return,
                    "lot_number": detail.lot_number
                })

        else:
            # Decisión 2 (dejar): 'ACEPTAR_RECEPCION', 'RECEPCION_CONFORME_FEFO',
            # 'INCIDENCIA_INTERNA' y cualquier acción de conformidad: se
            # acredita la porción conforme recibida en destino.
            credited_qty = conforming_qty
            _credit_inventory(inv_dest, credited_qty)

            # Reintegro al ORIGEN de la porción que no llegó (missing_qty):
            # el faltante que no se declaró como baja/extravío se considera
            # mercancía que nunca salió del abastecedor, por lo que vuelve
            # automáticamente a su inventario.
            if qty_missing > Decimal('0.00') and inv_origin is not None:
                current_origin = _to_decimal(inv_origin.current_quantity)
                inv_origin.current_quantity = current_origin + qty_missing

        resolution_items.append({
            "detail_id": detail.id,
            "product_id": detail.product_id,
            "action": action or "SIN_ACCION",
            "credited_qty": float(credited_qty),
            "return_qty": float(qty_to_return)
        })

    # 2. Procesar resoluciones sobre productos erróneos / fuera de guía
    for err_p in erroneous_products:
        prod_id = err_p.get("product_id")
        err_action = payload.get(f"erroneous_{prod_id}_action")
        qty_err = _to_decimal(err_p.get("quantity_delivered", 0))

        if not prod_id or qty_err <= Decimal('0.00'):
            continue

        if err_action == 'RESOLUCION_ACREDITAR_DESTINO':
            inv_dest_err = _get_or_create_inventory(movement.destination_location_id, prod_id)
            inv_dest_err.current_quantity = _to_decimal(inv_dest_err.current_quantity) + qty_err

            inv_orig_err = _get_or_create_inventory(movement.origin_location_id, prod_id)
            inv_orig_err.current_quantity = max(Decimal('0.00'), _to_decimal(inv_orig_err.current_quantity) - qty_err)

        elif err_action in RETURN_ACTIONS:
            has_returns = True
            return_items_payload.append({
                "product_id": prod_id,
                "quantity": qty_err,
                "lot_number": err_p.get("lot_number")
            })

        elif err_action in WRITE_OFF_ACTIONS:
            inv_orig_err = _get_or_create_inventory(movement.origin_location_id, prod_id)
            inv_orig_err.current_quantity = max(Decimal('0.00'), _to_decimal(inv_orig_err.current_quantity) - qty_err)

    # 3. Automatización de Movimiento Vinculado (Move and Links):
    # Si se marcaron devoluciones físicas, se genera un contra-movimiento de
    # traslado en tránsito hacia el origen (aparecerá en la bandeja Arbitraje).
    if has_returns and return_items_payload:
        linked_movement = Movement(
            type='RETORNO_EMERGENCIA',
            origin_location_id=movement.destination_location_id,
            destination_location_id=movement.origin_location_id,
            status='EN_TRANSITO',
            # OJO: 'source_dispute_id' es un campo distinto, reservado para el
            # despacho de REPOSICIÓN ("Ir a Reposición"). El RETORNO FÍSICO usa
            # 'return_of_dispute_id' para no pisar esa relación (ver
            # cancel_linked_replenishment más abajo).
            return_of_dispute_id=movement.id,
            user_id=user_id,
            resolution_notes=f"Retorno automático por resolución de disputa en traslado #{movement.id}. {general_notes}"
        )
        db.session.add(linked_movement)
        db.session.flush()  # Para obtener el ID del nuevo movimiento
        linked_return_movement_id = linked_movement.id

        for ret_item in return_items_payload:
            detail_entry = MovementDetail(
                movement_id=linked_movement.id,
                product_id=ret_item["product_id"],
                quantity=ret_item["quantity"],
                lot_number=ret_item.get("lot_number")
            )
            db.session.add(detail_entry)

            # BUGFIX: dejamos registrada la salida física en la sede que
            # devuelve (transit_quantity), igual que cualquier despacho normal.
            # Sin esto, el traslado de retorno quedaba "flotando" y al recibirlo
            # del otro lado no había nada que descontar en origen.
            return_origin_inv = _get_or_create_inventory(linked_movement.origin_location_id, ret_item["product_id"])
            return_origin_inv.transit_quantity = _to_decimal(return_origin_inv.transit_quantity) + ret_item["quantity"]

    # 4. Finalizar disputa, bitácora de auditoría y guardar
    movement.status = 'COMPLETADO'
    movement.resolution_notes = general_notes
    movement.resolved_by_id = user_id

    db.session.add(AuditLog(
        affected_table='movements',
        action='RESOLUCION_DISPUTA',
        severity='ALERTA' if has_returns else 'NORMAL',
        user_id=user_id,
        changed_data={
            "movement_id": movement.id,
            "event": "RESOLUCION_DISPUTA",
            "general_notes": general_notes,
            "items": resolution_items,
            "linked_return_movement_id": linked_return_movement_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    ))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


# ---------------------------------------------------------------------------
# CANCELACIÓN DE REPOSICIÓN COMPLEMENTARIA
# ---------------------------------------------------------------------------

def cancel_linked_replenishment(movement_id):
    """Cancela el traslado de reposición de una disputa y devuelve el stock.

    Devuelve (ok, message). Eleva excepciones si algo falla.
    """
    linked_replenishments = Movement.query.filter_by(
        source_dispute_id=movement_id,
        status='EN_TRANSITO'
    ).all()

    if not linked_replenishments:
        return True, "No hay reposiciones pendientes por cancelar."

    for mov in linked_replenishments:
        mov.status = 'CANCELADO'
        for detail in mov.details:
            inv = Inventory.query.filter_by(
                location_id=mov.origin_location_id,
                product_id=detail.product_id
            ).first()
            if inv:
                q_det = _to_decimal(detail.quantity)
                inv.current_quantity = _to_decimal(inv.current_quantity) + q_det
                if inv.transit_quantity is not None:
                    curr_transit = _to_decimal(inv.transit_quantity)
                    if curr_transit >= q_det:
                        inv.transit_quantity = curr_transit - q_det

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return True, "Traslado complementario cancelado y stock devuelto al origen."