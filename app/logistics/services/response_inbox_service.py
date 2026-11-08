from app.logistics.repositories.response_inbox_repository import ResponseInboxRepository


class ResponseInboxService:

    @staticmethod
    def get_responses_for_user(user):
        """Obtiene los traslados que ya contienen una respuesta del administrador."""
        return ResponseInboxRepository.get_admin_responses(user)

    @staticmethod
    def _product_line(item):
        name = item.get("product_name") or "Producto N/D"
        lot = item.get("lot_number")
        qty = item.get("dispatched_qty") or item.get("quantity")
        base = name + (f" (lote {lot})" if lot else "")
        if qty is not None:
            base += " x" + str(qty)
        return base

    @staticmethod
    def _serialize(mov):
        """Serializa un movimiento-respuesta para el JSON de la campana."""
        origin_name = getattr(mov.origin_location, "name", None) or f"Sede #{mov.origin_location_id}"
        dest_name = getattr(mov.destination_location, "name", None) or f"Sede #{mov.destination_location_id}"

        products = [
            {
                "product_name": it.get("product_name"),
                "lot_number": it.get("lot_number"),
                "dispatched_qty": it.get("dispatched_qty"),
                "received_qty": it.get("received_qty"),
                "missing_qty": it.get("missing_qty"),
                "specific_novelty": it.get("specific_novelty"),
            }
            for it in mov.novedad_items
        ]

        summary = mov.resolution_summary or {}
        totals = {
            "credited": summary.get("credited_total", 0),
            "returned": summary.get("returned_total", 0),
            "lost": summary.get("lost_total", 0),
        }

        return {
            "id": mov.id,
            "status": mov.status,
            "is_read": bool(getattr(mov, "is_read", True)),
            "origin": origin_name,
            "destination": dest_name,
            "movement_date": mov.date.strftime("%Y-%m-%d") if mov.date else None,
            "novedad": getattr(mov, "novedad_label", None) or "Novedad",
            "novedad_type": getattr(mov, "novedad_type", None),
            "products": products,
            "product_count": len(products),
            "resolution_date": mov.response_date.isoformat() if mov.response_date else None,
            "resolution_totals": totals,
            "notes": (mov.resolution_notes or "")[:160],
            "resolved_by": getattr(mov.response_by, "name", None) or "Administración",
            "reported_by": getattr(mov.reported_by, "name", None),
        }

    @staticmethod
    def get_inbox_summary(user, limit=50):
        """Resumen JSON para la campana de los receptores de traslados.

        Devuelve las respuestas más recientes (ligeras, sin datos sensibles)
        junto con el contador de pendientes de leer calculado en el servidor
        (tabla notifications). El estado "leído" ya NO vive en el navegador.
        """
        responses = ResponseInboxRepository.get_admin_responses(user, limit=limit)
        return {
            "total": len(responses),
            "unread_count": ResponseInboxRepository.get_unread_count(user),
            "items": [ResponseInboxService._serialize(mov) for mov in responses],
        }

    @staticmethod
    def mark_as_read(user, movement_id):
        """Marca leída la respuesta de un traslado para el usuario."""
        return ResponseInboxRepository.mark_as_read(user, movement_id)

    @staticmethod
    def mark_all_as_read(user):
        """Marca todas las respuestas del usuario como leídas."""
        return ResponseInboxRepository.mark_all_as_read(user)