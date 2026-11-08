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
    def _serialize(resp):
        """Serializa una respuesta de TRASLADO para el JSON de la campana."""
        origin_name = getattr(resp.origin_location, "name", None) or f"Sede #{resp.origin_location_id}"
        dest_name = getattr(resp.destination_location, "name", None) or f"Sede #{resp.destination_location_id}"

        products = [
            {
                "product_name": it.get("product_name"),
                "lot_number": it.get("lot_number"),
                "dispatched_qty": it.get("dispatched_qty"),
                "received_qty": it.get("received_qty"),
                "missing_qty": it.get("missing_qty"),
                "specific_novelty": it.get("specific_novelty"),
            }
            for it in resp.novedad_items
        ]

        summary = resp.resolution_summary or {}
        totals = {
            "credited": summary.get("credited_total", 0),
            "returned": summary.get("returned_total", 0),
            "lost": summary.get("lost_total", 0),
        }

        return {
            "id": resp.id,
            "response_type": getattr(resp, "response_type", None) or "TRASLADO",
            "status": resp.status,
            "is_read": bool(getattr(resp, "is_read", True)),
            "origin": origin_name,
            "destination": dest_name,
            "movement_date": resp.date.strftime("%Y-%m-%d") if resp.date else None,
            "novedad": getattr(resp, "novedad_label", None) or "Novedad",
            "novedad_type": getattr(resp, "novedad_type", None),
            "products": products,
            "product_count": len(products),
            "resolution_date": resp.response_date.isoformat() if resp.response_date else None,
            "resolution_totals": totals,
            "notes": (resp.resolution_notes or "")[:160],
            "resolved_by": getattr(resp.response_by, "name", None) or "Administración",
            "reported_by": getattr(resp.reported_by, "name", None),
        }

    @staticmethod
    def _serialize_waste(resp):
        """Serializa una respuesta de MERMA para el JSON de la campana."""
        loc = getattr(resp, "location", None)
        products = [
            {
                "product_name": it.get("product_name"),
                "lot_number": it.get("lot_number"),
                "quantity": it.get("quantity"),
            }
            for it in getattr(resp, "waste_details", []) or []
        ]
        return {
            "id": resp.id,
            "response_type": "MERMA",
            "status": resp.decision,
            "is_read": bool(getattr(resp, "is_read", True)),
            "origin": getattr(loc, "name", None) or f"Sede #{getattr(resp, 'location_id', None)}",
            "destination": "",
            "movement_date": resp.date.strftime("%Y-%m-%d") if resp.date else None,
            "novedad": getattr(resp, "decision_label", None) or "Merma",
            "novedad_type": getattr(resp, "novedad_type", None),
            "products": products,
            "product_count": len(products),
            "resolution_date": resp.response_date.isoformat() if resp.response_date else None,
            "resolution_totals": {},
            "notes": (
                (resp.rejection_reason or resp.waste_notes or "")[:160]
            ),
            "resolved_by": getattr(resp.response_by, "name", None) or "Administrador",
            "reported_by": getattr(resp.reported_by, "name", None),
            "total_quantity": float(getattr(resp, "total_quantity", 0) or 0),
            "waste_type_name": getattr(resp, "waste_type_name", None),
        }

    @staticmethod
    def get_inbox_summary(user, limit=50):
        """Resumen JSON para la campana (traslados + mermas).

        Devuelve las respuestas más recientes (ligeras, sin datos sensibles)
        junto con el contador de pendientes de leer calculado en el servidor
        (tabla notifications). El estado "leído" ya NO vive en el navegador.
        """
        responses = ResponseInboxRepository.get_admin_responses(user)
        items = []
        for resp in responses[:limit]:
            if getattr(resp, "response_type", None) == "MERMA":
                items.append(ResponseInboxService._serialize_waste(resp))
            else:
                items.append(ResponseInboxService._serialize(resp))
        return {
            "total": len(responses),
            "unread_count": ResponseInboxRepository.get_unread_count(user),
            "items": items,
        }

    @staticmethod
    def mark_as_read(user, movement_id):
        """Marca leída la respuesta de un traslado para el usuario."""
        return ResponseInboxRepository.mark_as_read(user, movement_id)

    @staticmethod
    def mark_waste_as_read(user, waste_id):
        """Marca leída la respuesta de una merma para el usuario."""
        return ResponseInboxRepository.mark_waste_as_read(user, waste_id)

    @staticmethod
    def mark_all_as_read(user):
        """Marca todas las respuestas del usuario como leídas."""
        return ResponseInboxRepository.mark_all_as_read(user)