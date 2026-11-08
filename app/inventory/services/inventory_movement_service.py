from datetime import datetime, timezone
from app.extensions import db
from app.models.inventory_model import Inventory
from sqlalchemy.orm.attributes import flag_modified
from app.inventory.repositories.inventory_movement_repository import obtener_movimiento_por_id
from app.inventory.requests.inventory_movement_validators import validar_plazo_edicion, validar_suficiencia_inventario

def procesar_edicion_movimiento(movimiento_id, nueva_cantidad_editada, motivo_edicion, usuario):
    movimiento = obtener_movimiento_por_id(movimiento_id)
    
    validar_plazo_edicion(movimiento.timestamp, usuario)
    
    datos_viejos = movimiento.changed_data
    location_id = datos_viejos.get('location_id')
    product_id = datos_viejos.get('product_id')
    cantidad_anterior = float(datos_viejos.get('quantity_subtracted', 0))
    nueva_cantidad_editada = float(nueva_cantidad_editada)
    
    inventario_actual = Inventory.query.filter_by(location_id=location_id, product_id=product_id).first()
    
    validar_suficiencia_inventario(inventario_actual, cantidad_anterior, nueva_cantidad_editada)
    
    diferencia = nueva_cantidad_editada - cantidad_anterior
    inventario_actual.current_quantity -= diferencia
    
    movimiento.changed_data['quantity_subtracted'] = nueva_cantidad_editada
    movimiento.changed_data['edit_reason'] = motivo_edicion
    movimiento.changed_data['edited_by_user_id'] = usuario.id
    movimiento.changed_data['edited_at'] = datetime.now(timezone.utc).isoformat()
    
    movimiento.severity = 'EDITADO'
    
    flag_modified(movimiento, "changed_data")
    
    db.session.commit()
    return True