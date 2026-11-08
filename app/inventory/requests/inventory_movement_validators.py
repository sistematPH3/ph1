from datetime import datetime, timezone

def validar_plazo_edicion(timestamp_movimiento, usuario):
    """
    Verifica que la edición ocurra dentro de los plazos permitidos según el rol.
    - Director/Gerente: 24 horas.
    - Administrador: 2 meses (aprox 60 días).
    """
    tiempo_transcurrido = datetime.now(timezone.utc) - timestamp_movimiento.replace(tzinfo=timezone.utc)
    horas_transcurridas = tiempo_transcurrido.total_seconds() / 3600
    
    if not usuario.is_admin:
        if horas_transcurridas > 24:
            raise ValueError("El plazo de 24 horas para editar este movimiento ha expirado. Contacte al Administrador.")
    else:
        if horas_transcurridas > (60 * 24):
            raise ValueError("El movimiento excede el plazo máximo de 2 meses para modificaciones.")

def validar_suficiencia_inventario(inventario_actual, cantidad_anterior, nueva_cantidad):
    """
    Verifica que la sede tenga stock suficiente para cubrir el ajuste.
    Si se gastó más de lo reportado originalmente, hay que restar la diferencia.
    """
    diferencia = nueva_cantidad - cantidad_anterior
    
    if diferencia > 0:
        if not inventario_actual or inventario_actual.current_quantity < diferencia:
            stock_disponible = inventario_actual.current_quantity if inventario_actual else 0
            raise ValueError(f"Inventario insuficiente: Quedan {stock_disponible} unidades, no cubre la diferencia de {diferencia}.")