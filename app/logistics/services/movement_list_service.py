from app.models import Movement, Location, Product

def get_movement_list_context(current_user):
    """
    Orquesta los datos de traslados activos para el listado operativo.
    - Admin: Ve todo el flujo operativo global sin restricciones de sedes.
    - Otros roles: Solo ven su(s) sede(s) asignada(s).

    Bandeja 'Arbitraje': NO es un status. Es cualquier traslado EN_TRANSITO
    cuyo return_of_dispute_id no es nulo -- es decir, el "contra-movimiento" de
    retorno físico que crea movement_dispute_routes.py (resolve_dispute) al
    resolver una disputa con RETORNO_EMERGENCIA / RESOLUCION_REINTEGRO. Ese
    traslado va exclusivamente a esta bandeja (no a 'por_recibir') porque
    quien lo recibe debe volver a evaluar novedades sobre la mercancía que
    regresa, no tratarlo como un despacho entrante normal.
    """
    user_loc_ids = [loc.id for loc in current_user.locations]

    # Base query de traslados operativos. 'EN_ARBITRAJE' no existe como status
    # real en ningún flujo (ver movement_dispute_routes.py / novelty catalog),
    # así que se quita del filtro.
    query = Movement.query.filter(Movement.status.in_(['EN_TRANSITO', 'COMPLETADO', 'CANCELADO_EMISOR']))

    # Aplicar filtro de sede SOLO si no es Administrador
    if not current_user.is_admin:
        query = query.filter(
            (Movement.origin_location_id.in_(user_loc_ids)) | 
            (Movement.destination_location_id.in_(user_loc_ids))
        )

    all_movements = query.order_by(Movement.date.desc()).all()

    # Mapear sedes dinámicamente en memoria
    locations_map = {loc.id: loc for loc in Location.query.all()}
    products_map = {p.id: p for p in Product.query.all()}

    for mov in all_movements:
        mov.origin_location = locations_map.get(mov.origin_location_id)
        mov.destination_location = locations_map.get(mov.destination_location_id)

        for item in mov.details:
            item.product = products_map.get(item.product_id)

    def is_dispute_return(m):
        # OJO: 'source_dispute_id' es un campo distinto, reservado para el
        # despacho de REPOSICIÓN. El retorno físico usa 'return_of_dispute_id'.
        return m.return_of_dispute_id is not None

    # Segmentación por estado. Los retornos de arbitraje (return_of_dispute_id
    # presente) se separan de los despachos EN_TRANSITO normales.
    #
    # REGLA DE VISIBILIDAD: los retornos de disputa SIEMPRE tienen como destino
    # el Almacén Central (sede fija, location id 1). Por decisión de negocio,
    # esta bandeja es EXCLUSIVA del Administrador: aunque los admins no tengan
    # sedes asignadas, ven todos los retornos (los gerentes NO).
    if current_user.is_admin:
        en_camino_list = [m for m in all_movements if m.status == 'EN_TRANSITO' and not is_dispute_return(m)]
        por_recibir_list = [m for m in all_movements if m.status == 'EN_TRANSITO' and not is_dispute_return(m)]
        arbitraje_list = [m for m in all_movements if m.status == 'EN_TRANSITO' and is_dispute_return(m)]
    else:
        en_camino_list = [
            m for m in all_movements
            if m.status == 'EN_TRANSITO' and m.origin_location_id in user_loc_ids and not is_dispute_return(m)
        ]
        por_recibir_list = [
            m for m in all_movements
            if m.status == 'EN_TRANSITO' and m.destination_location_id in user_loc_ids and not is_dispute_return(m)
        ]
        # Los gerentes NO ven la bandeja de arbitraje (retornos al Almacén Central).
        arbitraje_list = []

    return {
        "user_location_ids": user_loc_ids,
        "en_camino": en_camino_list,
        "por_recibir": por_recibir_list,
        "arbitraje": arbitraje_list,
        "historico": [m for m in all_movements if m.status in ['COMPLETADO', 'CANCELADO_EMISOR']]
    }