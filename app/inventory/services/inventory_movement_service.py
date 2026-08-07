from datetime import datetime, timezone
from app.extensions import db
from app.models.inventory_model import Inventory
from sqlalchemy.orm.attributes import flag_modified
from app.inventory.repositories.inventory_movement_repository import obtener_movimiento_por_id
from app.inventory.requests.inventory_movement_validators import validar_plazo_edicion, validar_suficiencia_inventario

def procesar_edicion_movimiento(movimiento_id, nueva_cantidad_editada, motivo_edicion, usuario):
    movimiento = obtener_movimiento_por_id(movimiento_id)
    
    # 1. Validar reglas de tiempo (Llama al archivo requests)
    validar_plazo_edicion(movimiento.timestamp, usuario)
    
    # 2. Extraer los datos guardados en el JSON del registro
    datos_viejos = movimiento.changed_data
    location_id = datos_viejos.get('location_id')
    product_id = datos_viejos.get('product_id')
    cantidad_anterior = float(datos_viejos.get('quantity_subtracted', 0))
    nueva_cantidad_editada = float(nueva_cantidad_editada)
    
    # 3. Consultar stock actual real de la sede
    inventario_actual = Inventory.query.filter_by(location_id=location_id, product_id=product_id).first()
    
    # 4. Validar reglas de stock (Llama al archivo requests)
    validar_suficiencia_inventario(inventario_actual, cantidad_anterior, nueva_cantidad_editada)
    
    # 5. Aplicar la modificación al stock real de la sede
    diferencia = nueva_cantidad_editada - cantidad_anterior
    inventario_actual.current_quantity -= diferencia
    
    # 6. Actualizar el registro para dejar rastro de la edición
    movimiento.changed_data['quantity_subtracted'] = nueva_cantidad_editada
    movimiento.changed_data['edit_reason'] = motivo_edicion
    movimiento.changed_data['edited_by_user_id'] = usuario.id
    movimiento.changed_data['edited_at'] = datetime.now(timezone.utc).isoformat()
    
    # Obligatorio para que SQLAlchemy detecte que un JSON interno fue modificado
    flag_modified(movimiento, "changed_data")
    
    db.session.commit()
    return True