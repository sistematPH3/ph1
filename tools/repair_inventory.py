"""
REPARACIÓN DEL INVENTARIO MAL CONTADO POR DISPUTAS (HISTÓRICAS Y RECIENTES).

DOS PROBLEMAS QUE ESTE SCRIPT ATIENDE
-------------------------------------
A) DISPUTAS RESUELTAS ANTES DEL FIX (solo afectadas por crédito en destino):
   El flujo viejo NUNCA acreditaba el inventario de la sede destino cuando la
   recepción registró novedad, aunque la mercancía conforme hubiera llegado
   físicamente. La sede quedó en 0 y el faltante no volvió a ningún lado.

B) RESOLUCIONES CON "DEVOLVER" QUE NO CREARON EL RETORNO (bug del rechazo):
   Al resolver con RETORNO_EMERGENCIA / RETORNO_EMERGENCIA(por espacio), el
   qty_to_return se calculaba como extra_units + missing_qty = 0 cuando la
   cantidad recibida coincidía con la despachada, así que NO se creaba el
   movimiento de retorno y la mercancía quedaba "sin documento". El script
   detecta esas resoluciones y (con --apply) MATERIALIZA el retorno pendiente.

REGLAS DE NEGOCIO (según indicación del usuario)
------------------------------------------------
- FALTANTE (autorizado 10, llegaron 8):
    * Los 8 conformes se acreditan SIEMPRE a la sede destino (nunca fueron
      acreditados por el código viejo: ajuste 100% seguro).
    * Los 2 faltantes: o se declaran EXTRAVÍO (desaparecen) o, al no declararse
      extravío, vuelven automáticamente al inventario de ORIGEN. Reponer al
      origen es el comportamiento por defecto aquí; use --extraviar-faltantes
      para NO reponer nada a origen (tratar todo como extravío/baja).
- SOBRANTE (autorizado 10, llegaron 15):
    * Los 10 conformes se acreditan SIEMPRE a la sede.
    * Los 5 extra NO se tocan: el admin decidió en su momento acreditarlos a la
      sede (ACREDITAR_DESTINO) o retornarlos (REINTEGRO -> RETORNO_EMERGENCIA).
      Si hay un RETORNO_EMERGENCIA vinculado, el retorno ya lo gestiona; si no
      lo hay, el código viejo ya acreditó el extra a la sede.
- Novedades de calidad (INCIDENCIA_TEMPERATURA / VIOLACION_CUSTODIA /
  LOTE_NO_COINCIDE) y RECHAZO_POR_ESPACIO / RETORNO_EMERGENCIA:
    * Sin retorno vinculado -> la mercancía se quedó en la sede: se acredita lo
      recibido al destino.
    * Con retorno vinculado -> la mercancía vuelve al origen: NO se acredita.
- Productos erróneos: NO se tocan (ya fueron acreditados o retornados por el
  código viejo); solo se reportan.

SEGURIDAD / IDEMPOTENCIA
------------------------
- DRY-RUN por defecto: solo consulta, no escribe nada.
- Use `--apply` para escribir. Cada ajuste se marca con AuditLog
  action=REPARACION_INVENTARIO (o RECREAR_RETORNO para retornos materializados),
  por lo que el script no se re-aplica sobre el mismo movimiento.
- No re-procesa movimientos ya resueltos correctamente con el flujo nuevo, salvo
  la detección B (devolución prometida sin retorno creado).

USO
---
    python tools/repair_inventory.py                # diagnóstico (solo lectura)
    python tools/repair_inventory.py --extraviar-faltantes       # diagnóstico
    python tools/repair_inventory.py --apply                     # aplicar
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import AuditLog, Inventory, Movement, MovementDetail

RECEPTION_NOVEDAD_ACTIONS = ('RECEPCION_NOVEDAD', 'RECEPCION_INCIDENCIA_CALIDAD')
RETURN_ACTIONS = ('RESOLUCION_REINTEGRO', 'RETORNO_EMERGENCIA')
QUALITATIVE_NOVELTY_TYPES = ('INCIDENCIA_TEMPERATURA', 'VIOLACION_CUSTODIA', 'LOTE_NO_COINCIDE')
RECHAZO_TYPES = ('RECHAZO_POR_ESPACIO', 'RETORNO_EMERGENCIA')

REPAIRED_ACTION = 'REPARACION_INVENTARIO'
RECREATED_RETURN_ACTION = 'RECREAR_RETORNO'


def _dec(value, default='0.00'):
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def _read_changed(entry):
    data = entry.changed_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return {}
    return data or {}


def _audits_by_movement(actions):
    """Devuelve {movement_id: entry} para acciones de auditoría determinadas."""
    by_mov = {}
    audits = AuditLog.query.filter(
        AuditLog.affected_table == 'movements',
        AuditLog.action.in_(actions),
    ).all()
    for entry in audits:
        data = _read_changed(entry)
        mid = data.get('movement_id')
        if mid is not None:
            by_mov.setdefault(int(mid), entry)
    return by_mov


def _linked_returns(movement_id):
    """Retornos físicos (RETORNO_EMERGENCIA) vinculados a la disputa."""
    movs = Movement.query.filter(
        Movement.type == 'RETORNO_EMERGENCIA',
        ((Movement.return_of_dispute_id == movement_id) |
         (Movement.source_dispute_id == movement_id)),
    ).all()
    return movs


def _get_or_create_inventory(location_id, product_id):
    inv = Inventory.query.filter_by(
        location_id=location_id, product_id=product_id
    ).first()
    if inv is None:
        inv = Inventory(location_id=location_id, product_id=product_id,
                        current_quantity=Decimal('0.00'),
                        transit_quantity=Decimal('0.00'))
        db.session.add(inv)
    return inv


# ---------------------------------------------------------------------------
# PARTE A: disputas resueltas antes del fix (crédito en destino ausente)
# ---------------------------------------------------------------------------

def build_survivor_candidates(recep_by_mov, resolved_ids, repaired_ids):
    movs = Movement.query.filter(
        Movement.type == 'DESPACHO',
        Movement.status == 'COMPLETADO',
    ).all()
    candidates = []
    for m in movs:
        if m.id not in recep_by_mov:
            continue
        if m.id in resolved_ids:
            # Resuelto con el flujo nuevo → no es candidato aquí (ver parte B).
            continue
        if m.id in repaired_ids:
            continue
        candidates.append(m)
    return candidates


def plan_movement(movement, recep_data, extraviar_faltantes):
    items = recep_data.get('items', [])

    dest_add = defaultdict(Decimal)
    origin_add = defaultdict(Decimal)
    per_item = []

    return_movs = _linked_returns(movement.id)
    has_return = bool(return_movs)
    return_pending = any(s.status == 'EN_TRANSITO' for s in return_movs)
    return_completed = any(s.status == 'COMPLETADO' for s in return_movs)
    return_cancelled = any(str(s.status).upper().startswith('CANCEL') for s in return_movs)

    if has_return and (return_pending or return_completed):
        returns_handle_stock = True
        return_state = return_movs[0].status
    elif has_return and return_cancelled:
        returns_handle_stock = False
        return_state = 'RETORNO_CANCELADO'
    else:
        returns_handle_stock = False
        return_state = return_movs[0].status if has_return else 'SIN_RETORNO'

    for it in items:
        product_id = int(it.get('product_id'))
        dispatched = _dec(it.get('dispatched_qty'))
        received = _dec(it.get('received_qty'))
        missing = _dec(it.get('missing_qty'))
        novelty = it.get('specific_novelty', it.get('item_condition', 'CONFORME'))
        lot = it.get('lot_number')

        conforming = min(received, dispatched)
        extra = max(Decimal('0.00'), received - dispatched)

        row = {
            'product_id': product_id,
            'sku': it.get('sku'),
            'product_name': it.get('product_name'),
            'lot_number': lot,
            'dispatched': dispatched,
            'received': received,
            'missing': missing,
            'extra': extra,
            'novelty': novelty,
            'credito_destino': Decimal('0.00'),
            'retorno_origen': Decimal('0.00'),
            'nota': '',
        }

        # CRÉDITO EN DESTINO (porción conforme).
        skip_dest = False
        if novelty in QUALITATIVE_NOVELTY_TYPES and returns_handle_stock:
            skip_dest = True
            row['nota'] = 'Calidad/Rechazo devuelto via RETORNO (no se acredita en sede)'
        if not skip_dest and conforming > 0:
            dest_add[(movement.destination_location_id, product_id)] += conforming
            row['credito_destino'] = conforming

        # REINTEGRO AL ORIGEN (faltante).
        if missing > 0:
            if returns_handle_stock:
                row['nota'] = 'Faltante gestionado por el retorno (no se repone en origen)'
            elif return_state == 'RETORNO_CANCELADO':
                row['nota'] = 'FALTANTE ATASCADO: retorno creado y CANCELADO. Revisar manualmente.'
            elif extraviar_faltantes:
                row['nota'] = 'Extravío/baja: el faltante desaparece (no se repone en origen)'
            else:
                origin_add[(movement.origin_location_id, product_id)] += missing
                row['retorno_origen'] = missing
                row['nota'] = 'Faltante sin retorno -> se repone en el inventario de ORIGEN'

        if extra > 0:
            if returns_handle_stock:
                row['nota'] += ' | Extra gestionado por el retorno.'
            else:
                row['nota'] += ' | Extra ya acreditado a la sede por el codigo viejo (ACREDITAR).'

        per_item.append(row)

    return {
        'kind': 'HISTORICO',
        'movement_id': movement.id,
        'origin_location_id': movement.origin_location_id,
        'destination_location_id': movement.destination_location_id,
        'return_state': return_state,
        'per_item': per_item,
        'dest_add': dict(dest_add),
        'origin_add': dict(origin_add),
    }


# ---------------------------------------------------------------------------
# PARTE B: resoluciones con "devolver" que no materializaron el retorno
# ---------------------------------------------------------------------------

def build_phantom_return_candidates(resolved_entries, recep_by_mov, recreated_ids):
    """Movimientos resueltos con flujo nuevo donde se ordenó devolver pero el
    RETORNO_EMERGENCIA nunca se creó (qty_to_return calculado en 0)."""
    candidates = []
    for mov_id, entry in resolved_entries.items():
        if mov_id in recreated_ids:
            continue
        data = _read_changed(entry)
        items = data.get('items', [])
        linked_return_movement_id = data.get('linked_return_movement_id')

        has_return_action = any(
            str(it.get('action')) in RETURN_ACTIONS for it in items
        )
        if not has_return_action:
            continue
        if linked_return_movement_id:
            continue
        if _linked_returns(mov_id):
            continue

        movement = Movement.query.get(mov_id)
        if not movement or movement.status != 'COMPLETADO':
            continue

        recep = _read_changed(recep_by_mov.get(mov_id)) if mov_id in recep_by_mov else {}
        items_by_detail = {int(it.get('detail_id')): it for it in recep.get('items', [])}

        owed = []
        for it in items:
            action = str(it.get('action'))
            if action not in RETURN_ACTIONS:
                continue
            detail_id = it.get('detail_id')
            recv = _dec(items_by_detail.get(int(detail_id), {}).get('received_qty'))
            dispatched = _dec(items_by_detail.get(int(detail_id), {}).get('dispatched_qty'))
            missing = _dec(items_by_detail.get(int(detail_id), {}).get('missing_qty'))
            novelty = (items_by_detail.get(int(detail_id), {}).get('specific_novelty') or '')

            extra = max(Decimal('0.00'), recv - dispatched)
            if novelty in QUALITATIVE_NOVELTY_TYPES or novelty in RECHAZO_TYPES:
                qty = recv
            else:
                qty = extra + missing
            owed.append({
                'product_id': int(it.get('product_id')),
                'lot_number': items_by_detail.get(int(detail_id), {}).get('lot_number'),
                'quantity': qty,
                # El código intermedio (pre-fix de rechazo) ACREDITÓ esta cantidad
                # a la sede destino aunque el admin ordenó devolverla toda. Hay
                # que revertirla de la sede y luego materializar el retorno.
                'credited_qty': _dec(it.get('credited_qty')),
            })

        if not owed or all(_dec(o['quantity']) <= 0 for o in owed):
            continue

        candidates.append({
            'movement_id': mov_id,
            'dispute': movement,
            'owed': owed,
            'return_state': 'RETORNO_NO_CREADO',
        })
    return candidates


def create_return_for_phantom(cand):
    """Crea el RETORNO_EMERGENCIA que la resolución prometió pero no materializó."""
    dispute = cand['dispute']
    linked = Movement(
        type='RETORNO_EMERGENCIA',
        origin_location_id=dispute.destination_location_id,
        destination_location_id=dispute.origin_location_id,
        status='EN_TRANSITO',
        return_of_dispute_id=dispute.id,
        user_id=None,
        resolution_notes=(f"Retorno recreado por reparación: resolución de la disputa "
                          f"#{dispute.id} ordenó devolver pero no se creó el traslado."),
    )
    db.session.add(linked)
    db.session.flush()

    details = []
    reversions = []
    for o in cand['owed']:
        qty = _dec(o['quantity'])
        if qty <= 0:
            continue

        # REVERTIR el crédito indebido que la sede recibió (mercancía rechazada).
        revert_qty = _dec(o['credited_qty'])
        if revert_qty > 0:
            inv_dest = Inventory.query.filter_by(
                location_id=dispute.destination_location_id,
                product_id=o['product_id'],
            ).first()
            if inv_dest is not None:
                before = inv_dest.current_quantity
                inv_dest.current_quantity = max(Decimal('0.00'),
                                                _dec(inv_dest.current_quantity) - revert_qty)
                reversions.append({
                    'product_id': o['product_id'],
                    'cantidad': float(revert_qty),
                    'current_antes': float(before),
                    'current_despues': float(inv_dest.current_quantity),
                })

        detail = MovementDetail(
            movement_id=linked.id,
            product_id=o['product_id'],
            quantity=qty,
            lot_number=o.get('lot_number'),
        )
        db.session.add(detail)
        details.append({
            'movement_id': linked.id,
            'detail_id': detail.id,
            'product_id': o['product_id'],
            'quantity': float(qty),
        })
        inv = _get_or_create_inventory(linked.origin_location_id, o['product_id'])
        inv.transit_quantity = _dec(inv.transit_quantity) + qty

    db.session.add(AuditLog(
        affected_table='movements',
        action=RECREATED_RETURN_ACTION,
        severity='ALERTA',
        user_id=None,
        location_id=dispute.destination_location_id,
        changed_data={
            'movement_id': dispute.id,
            'event': RECREATED_RETURN_ACTION,
            'linked_return_movement_id': linked.id,
            'details': details,
            'reversions_destino': reversions,
        },
    ))
    return linked, details, reversions


# ---------------------------------------------------------------------------
# Aplicación y reporte
# ---------------------------------------------------------------------------

def apply_survivor(plan):
    movement_id = plan['movement_id']
    changes = []
    for (location_id, product_id), qty in sorted(plan['dest_add'].items()):
        if qty <= 0:
            continue
        inv = _get_or_create_inventory(location_id, product_id)
        before = inv.current_quantity
        inv.current_quantity = _dec(inv.current_quantity) + qty
        changes.append({
            'location_id': location_id, 'product_id': product_id,
            'concepto': 'CREDITO_DESTINO_CONFORME',
            'cantidad': float(qty),
            'current_antes': float(before),
            'current_despues': float(inv.current_quantity),
        })

    for (location_id, product_id), qty in sorted(plan['origin_add'].items()):
        if qty <= 0:
            continue
        inv = _get_or_create_inventory(location_id, product_id)
        before = inv.current_quantity
        inv.current_quantity = _dec(inv.current_quantity) + qty
        changes.append({
            'location_id': location_id, 'product_id': product_id,
            'concepto': 'REINTEGRO_ORIGEN_FALTANTE',
            'cantidad': float(qty),
            'current_antes': float(before),
            'current_despues': float(inv.current_quantity),
        })

    db.session.add(AuditLog(
        affected_table='movements',
        action=REPAIRED_ACTION,
        severity='ALERTA',
        user_id=None,
        location_id=plan['destination_location_id'],
        changed_data={
            'movement_id': movement_id,
            'event': REPAIRED_ACTION,
            'return_state': plan['return_state'],
            'changes': changes,
            'per_item': [{
                'product_id': r['product_id'],
                'novelty': r['novelty'],
                'credito_destino': float(r['credito_destino']),
                'retorno_origen': float(r['retorno_origen']),
                'nota': r['nota'],
            } for r in plan['per_item']],
        },
    ))
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise RuntimeError(f'Movimiento #{movement_id}: no se pudo aplicar: {exc}')
    return len(changes)


def print_survivor(plan):
    total_dest = sum(plan['dest_add'].values(), Decimal('0.00'))
    total_origin = sum(plan['origin_add'].values(), Decimal('0.00'))
    print(f"\nMovimiento #{plan['movement_id']} (HISTORICO) | "
          f"Origen: {plan['origin_location_id']} -> Destino: {plan['destination_location_id']} | "
          f"Retorno: {plan['return_state']}")
    print('-' * 110)
    header = (f"{'SKU':<18}{'Producto':<30}{'Nov':<20}{'Desp':>8}{'Recib':>8}{'Falt':>7}{'Extra':>7}"
              f" | {'Credito Sede':>14} | {'Retorno Origen':>16} | Nota")
    print(header)
    for r in plan['per_item']:
        name = (r['product_name'] or '')[:30]
        sku = (r['sku'] or str(r['product_id']))[:18]
        print(f"{sku:<18}{name:<30}{str(r['novelty'])[:20]:<20}"
              f"{float(r['dispatched']):>8.0f}{float(r['received']):>8.0f}"
              f"{float(r['missing']):>7.0f}{float(r['extra']):>7.0f}"
              f" | {float(r['credito_destino']):>14.0f}"
              f" | {float(r['retorno_origen']):>16.0f} | {r['nota'][:55]}")
    print(f"  TOTALES MOVIMIENTO: +{total_dest:.2f} en sede destino | +{total_origin:.2f} en origen")
    return total_dest, total_origin


def main():
    parser = argparse.ArgumentParser(description='Reparación de inventario por disputas.')
    parser.add_argument('--apply', action='store_true',
                        help='Escribir cambios (por defecto solo diagnostica).')
    parser.add_argument('--extraviar-faltantes', action='store_true',
                        help='NO reponer a origen los faltantes: tratarlos como extravío/baja.')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print('Cargando auditorías de recepción...')
        recep_by_mov = _audits_by_movement(RECEPTION_NOVEDAD_ACTIONS)
        print(f'  Recepciones con novedad: {len(recep_by_mov)}')

        resolved_by_mov = _audits_by_movement(('RESOLUCION_DISPUTA',))
        print(f'  Disputas resueltas con el flujo nuevo: {len(resolved_by_mov)}')

        repaired_ids = set(_audits_by_movement((REPAIRED_ACTION,)).keys())
        recreated_ids = set(_audits_by_movement((RECREATED_RETURN_ACTION,)).keys())
        print(f'  Ya reparadas (excluidas): {len(repaired_ids)} | Ya con retorno recreado: {len(recreated_ids)}')

        # --------------------------- PARTE A -------------------------------
        print('\n' + '=' * 110)
        print('PARTE A - DISPUTAS RESUELTAS ANTES DEL FIX (crédito a destino ausente)')
        print('=' * 110)
        candidates_a = build_survivor_candidates(recep_by_mov, set(resolved_by_mov.keys()), repaired_ids)
        total_dest = Decimal('0.00')
        total_origin = Decimal('0.00')
        if not candidates_a:
            print('  No hay movimientos históricos pendientes de acreditar.')
        for m in candidates_a:
            plan = plan_movement(m, _read_changed(recep_by_mov[m.id]), args.extraviar_faltantes)
            if args.apply:
                n = apply_survivor(plan)
                print(f'  Aplicado #{m.id}: {n} ajustes.')
            else:
                d, o = print_survivor(plan)
                total_dest += d
                total_origin += o
        if not args.apply and candidates_a:
            print(f'\n  TOTAL PARTE A: +{total_dest:.2f} en sedes destino | +{total_origin:.2f} en origen')

        # --------------------------- PARTE B -------------------------------
        print('\n' + '=' * 110)
        print('PARTE B - RESOLUCIONES CON "DEVOLVER" QUE NO CREARON EL RETORNO')
        print('=' * 110)
        candidates_b = build_phantom_return_candidates(resolved_by_mov, recep_by_mov, recreated_ids)
        if not candidates_b:
            print('  No hay retornos prometidos sin materializar.')
        for cand in candidates_b:
            dispute = cand['dispute']
            print(f"\n  Disputa #{dispute.id} | {dispute.origin_location_id} -> "
                  f"{dispute.destination_location_id} | estado: {dispute.status}")
            print(f"  Se ordenó DEVOLVER, pero NO existe el movimiento RETORNO_EMERGENCIA "
                  f"(return_of_dispute_id=NULL). Plan de reparación:")
            for o in cand['owed']:
                qty = _dec(o['quantity'])
                rev = _dec(o['credited_qty'])
                if qty > 0:
                    print(f"    - Producto #{o['product_id']} x {float(qty):.2f} unidades")
                    if rev > 0:
                        print(f"      * Revertir {float(rev):.2f} unidades acreditadas de la sede destino "
                              f"(rechazo no debía quedarse)")
            if args.apply:
                linked, details, reversions = create_return_for_phantom(cand)
                print(f"  -> RETORNO RECREADO: #{linked.id} (EN_TRANSITO, {len(details)} ítem(s), "
                      f"{len(reversions)} reversión(es) en destino).")
                db.session.commit()
            else:
                print(f"  -> (No se creó nada: ejecute con --apply)")

        print('\n' + '=' * 110)
        if not args.apply:
            print('[DRY-RUN] No se escribió nada. Ejecute con --apply para aplicar los cambios.')
        else:
            print('Proceso terminado. Consulte los audits REPARACION_INVENTARIO / RECREAR_RETORNO.')


if __name__ == '__main__':
    main()