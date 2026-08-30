/* =========================================================
   CAMPANA DE RESPUESTAS DEL ADMINISTRADOR (RECEPTORES)
   -----------------------------------------------------------------
   Consulta en vivo el resumen de respuestas (/responses/summary).
   El contador de pendientes lo calcula el SERVIDOR (tabla notifications,
   is_read); NO se usa localStorage. Al hacer clic en una respuesta se
   marca como leída en el servidor y se navega a la bandeja.
   Cada aviso muestra # de traslado, clasificación de la novedad, ruta,
   fecha y productos, para identificarlo entre muchos traslados.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const bell = document.getElementById("responseBell");
    if (!bell) return;
    if (bell.dataset.enabled !== "true") return;

    const POLL_INTERVAL_MS = 30000;
    const MAX_LIST_ITEMS = 5;

    const pollUrl = bell.dataset.pollUrl;
    const inboxUrl = bell.dataset.inboxUrl;

    const btn = bell.querySelector(".response-bell-btn");
    const badge = bell.querySelector(".response-bell-badge");
    const panel = bell.querySelector(".response-bell-panel");
    const listEl = bell.querySelector(".response-bell-list");

    let items = [];
    let unreadCount = 0;

    /* ---------- Badge (dato del servidor) ---------- */
    function updateBadge() {
        if (unreadCount > 0) {
            badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
            badge.removeAttribute("hidden");
            btn.classList.add("has-unread");
        } else {
            badge.setAttribute("hidden", "");
            btn.classList.remove("has-unread");
        }
    }

    /* ---------- Escape de texto para inyectar HTML seguro ---------- */
    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    /* ---------- Descripción textual de los productos (resumida) ---------- */
    function productLine(item) {
        const prods = item.products || [];
        if (prods.length === 0) return "Sin detalle de productos";
        return prods
            .slice(0, 3)
            .map(function (p) {
                let s = escapeHtml(p.product_name || "Producto N/D");
                if (p.lot_number) s += " (" + escapeHtml(p.lot_number) + ")";
                return s;
            })
            .join(" · ") + (prods.length > 3 ? " · +" + (prods.length - 3) + " más" : "");
    }

    function totalsLine(item) {
        const t = item.resolution_totals || {};
        const parts = [];
        if (t.credited) parts.push("Acreditado: " + t.credited);
        if (t.returned) parts.push("Devuelto: " + t.returned);
        if (t.lost) parts.push("Perdido: " + t.lost);
        return parts.length ? parts.join(" · ") : "Respuesta emitida";
    }

    /* ---------- Render del panel ---------- */
    function renderList() {
        const unreadItems = items.filter(function (i) { return !i.is_read; });
        const shown = unreadItems.slice(0, MAX_LIST_ITEMS);

        if (shown.length === 0) {
            listEl.innerHTML = '<li class="response-bell-empty"><i class="bi bi-inbox"></i>No hay respuestas nuevas</li>';
            return;
        }

        listEl.innerHTML = "";
        shown.forEach(function (item) {
            const li = document.createElement("li");
            li.className = "response-bell-item";
            li.innerHTML =
                '<div class="response-bell-item-title"><i class="bi bi-truck me-1"></i>Traslado #' + item.id +
                ' <span class="response-bell-item-tag">' + escapeHtml(item.novedad || "Novedad") + '</span></div>' +
                '<div class="response-bell-item-sub">' + escapeHtml(item.origin) + ' \u2192 ' + escapeHtml(item.destination) + '</div>' +
                '<div class="response-bell-item-sub">' + escapeHtml(productLine(item)) + '</div>' +
                '<div class="response-bell-item-sub text-muted">' + (item.movement_date ? escapeHtml(item.movement_date) : "") + (item.resolved_by ? " \u00b7 " + escapeHtml(item.resolved_by) : "") + '</div>' +
                '<div class="response-bell-item-totals">' + escapeHtml(totalsLine(item)) + '</div>';
            li.addEventListener("click", function () {
                markRead(item.id);
                window.location.href = inboxUrl;
            });
            listEl.appendChild(li);
        });
    }

    /* ---------- Marcar leída en el servidor ---------- */
    function markRead(movementId) {
        fetch(pollUrl.replace(/\/summary$/, "/read"), {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ movement_id: movementId })
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && typeof data.unread_count === "number") {
                    unreadCount = data.unread_count;
                    items = items.map(function (i) {
                        return i.id === movementId ? Object.assign({}, i, { is_read: true }) : i;
                    });
                    updateBadge();
                }
            })
            .catch(function () { /* mejor esfuerzo */ });
    }

    /* ---------- Polling del resumen ---------- */
    async function poll() {
        let data;
        try {
            const res = await fetch(pollUrl, {
                headers: { "Accept": "application/json" },
                cache: "no-store",
                credentials: "same-origin"
            });
            if (!res.ok) return;
            const text = await res.text();
            data = text ? JSON.parse(text) : null;
        } catch (e) {
            return;
        }
        if (!data) return;

        const previousUnread = unreadCount;
        unreadCount = typeof data.unread_count === "number" ? data.unread_count : 0;
        items = data.items || [];
        updateBadge();

        // Si llega una respuesta nueva sin marcar leída: destello del botón.
        if (previousUnread === 0 && unreadCount > 0) {
            btn.classList.add("bell-shake");
            setTimeout(function () { btn.classList.remove("bell-shake"); }, 900);
        }

        // Si el panel está abierto, refrescarlo con los datos nuevos.
        if (!panel.hasAttribute("hidden")) {
            renderList();
        }
    }

    /* ---------- Abrir / cerrar el panel ---------- */
    btn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (panel.hasAttribute("hidden")) {
            renderList();
            panel.removeAttribute("hidden");
        } else {
            panel.setAttribute("hidden", "");
        }
    });

    document.addEventListener("click", function (e) {
        if (!bell.contains(e.target)) {
            panel.setAttribute("hidden", "");
        }
    });

    // Arranque casi inmediato y luego cada intervalo.
    setTimeout(poll, 800);
    setInterval(poll, POLL_INTERVAL_MS);
});