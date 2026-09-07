from app.time_utils import current_ve_time, TZ_VENEZUELA

def validar_plazo_edicion(timestamp_movimiento, usuario):
    """
    Verifica que la edición ocurra dentro de los plazos permitidos según el rol.
    - Director/Gerente: 24 horas.
    - Administrador: 2 meses (aprox 60 días).
    """
    ts_base = timestamp_movimiento
    if ts_base and ts_base.tzinfo is not None:
        ts_base = ts_base.astimezone(TZ_VENEZUELA).replace(tzinfo=None)

    tiempo_transcurrido = current_ve_time() - (ts_base or current_ve_time())
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
    Usa el stock DISPONIBLE (físico menos tránsito y mermas pendientes congeladas).
    """
    diferencia = nueva_cantidad - cantidad_anterior

    if diferencia > 0:
        if not inventario_actual:
            raise ValueError(f"Inventario insuficiente: no hay stock registrado para este insumo.")
        disponible = (
            float(inventario_actual.current_quantity or 0)
            - float(inventario_actual.transit_quantity or 0)
            - float(inventario_actual.reserved_quantity or 0)
        )
        if disponible < diferencia:
            raise ValueError(
                f"Inventario insuficiente: Quedan {disponible:.2f} unidades disponibles, "
                f"no cubren la diferencia de {diferencia:.2f}."
            )