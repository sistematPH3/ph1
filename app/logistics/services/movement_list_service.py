from app.models import Movement, Location, Product

def get_movement_list_context(current_user):
    """
    Orquesta los datos de traslados activos para el listado operativo.
    - Admin: Ve todo el flujo operativo global sin restricciones de sedes.
    - Otros roles: Solo ven su(s) sede(s) asignada(s).
    """
    user_loc_ids = [loc.id for loc in current_user.locations]
    
    # Base query de traslados operativos ('EN_TRANSITO' y 'COMPLETADO')
    query = Movement.query.filter(Movement.status.in_(['EN_TRANSITO', 'COMPLETADO', 'CANCELADO_EMISOR']))

    # Aplicar filtro de sede SOLO si no es Administrador
    if not current_user.is_admin:
        query = query.filter(
            (Movement.origin_location_id.in_(user_loc_ids)) | 
            (Movement.destination_location_id.in_(user_loc_ids))
        )
# 3. Asignación fuera de cualquier bloque IF (Alineado con el margen del método)
    all_movements = query.order_by(Movement.date.desc()).all()

    # 4. Mapear sedes dinámicamente en memoria
    locations_map = {loc.id: loc for loc in Location.query.all()}
    products_map = {p.id: p for p in Product.query.all()}

    for mov in all_movements:
        mov.origin_location = locations_map.get(mov.origin_location_id)
        mov.destination_location = locations_map.get(mov.destination_location_id)

        for item in mov.details:
            item.product = products_map.get(item.product_id)

    # Si es admin, ve TODO lo que esté en tránsito. Si no, filtra por su sede de origen o destino.
    if current_user.is_admin:
        en_camino_list = [m for m in all_movements if m.status == 'EN_TRANSITO']
        por_recibir_list = [m for m in all_movements if m.status == 'EN_TRANSITO']
    else:
        en_camino_list = [m for m in all_movements if m.status == 'EN_TRANSITO' and m.origin_location_id in user_loc_ids]
        por_recibir_list = [m for m in all_movements if m.status == 'EN_TRANSITO' and m.destination_location_id in user_loc_ids]

    return {
        "user_location_ids": user_loc_ids,
        "en_camino": en_camino_list,
        "por_recibir": por_recibir_list,
        "historico": [m for m in all_movements if m.status in ['COMPLETADO', 'CANCELADO_EMISOR']]
    }