from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.inventory.repositories.inventory_movement_repository import obtener_movimientos_resta
from app.inventory.services.inventory_movement_service import procesar_edicion_movimiento

inventory_movements_bp = Blueprint('inventory_movements', __name__, url_prefix='/inventory/movements')

@inventory_movements_bp.route('/subtractions', methods=['GET'])
@login_required
def listar_restas():
    # El repositorio ya se encarga de filtrar automáticamente según el rol
    movimientos = obtener_movimientos_resta()
    return render_template('inventory/subtractions_list.html', movimientos=movimientos)

@inventory_movements_bp.route('/subtractions/edit/<int:movimiento_id>', methods=['POST'])
@login_required
def editar_resta(movimiento_id):
    nueva_cantidad = request.form.get('nueva_cantidad', type=float)
    motivo = request.form.get('motivo_edicion')
    
    if nueva_cantidad is None or not motivo:
        flash("La nueva cantidad y el motivo de edición son obligatorios.", "warning")
        return redirect(url_for('inventory_movements.listar_restas'))
        
    try:
        # Se envía al servicio para ser procesado
        procesar_edicion_movimiento(movimiento_id, nueva_cantidad, motivo, current_user)
        flash("El movimiento fue editado y el stock actualizado correctamente.", "success")
    except ValueError as e:
        # Captura los "raise ValueError" de tu archivo requests (falta de tiempo o stock)
        flash(str(e), "danger")
    except Exception as e:
        flash("Ocurrió un error inesperado al procesar la edición.", "danger")
        
    return redirect(url_for('inventory_movements.listar_restas'))