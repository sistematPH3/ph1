/* =========================================================
   NOTIFICACIONES DE NOVEDADES / ARBITRAJE
   -----------------------------------------------------------------
   Mantiene en vivo:
     1. El círculo rojo del sidebar (nº de novedades pendientes).
     2. Avisos emergentes (toasts) que se muestran unos segundos y
        desaparecen cuando llega una novedad nueva a la bandeja.
   -----------------------------------------------------------------
   Como se recuerda lo ya visto:
     - Se guarda una lista de IDs de nas novedades ya anunciadas en
       localStorage, separada por usuario. Solo disparan toast los IDs
       que todavía no se habían anunciado (novedad "recién llegada").
   -----------------------------------------------------------------
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const container = document.getElementById("disputeToastContainer");
    if (!container) return;
    if (container.dataset.enabled !== "true") return;

    const POLL_INTERVAL_MS = 30000;   // consulta cada 30 segundos
    const TOAST_DURATION_MS = 6000;   // el aviso se esconde solo a los 6s
    const MAX_VISIBLE_TOASTS = 3;

    const pollUrl = container.dataset.pollUrl;
    const disputesUrl = container.dataset.disputesUrl;
    const userId = container.dataset.userId || "anon";
    const STORAGE_KEY = "ph_disputes_seen_" + userId;

    const badge = document.getElementById("disputeBadge");

    // El aviso por "pendientes" al abrir el dashboard solo aplica en /dashboard/*
    function isOnDashboard() {
        return window.location.pathname.indexOf("/dashboard") === 0;
    }

    /* ---------- Acceso a localStorage (soportado por todos) ---------- */
    function getSeen() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function setSeen(ids) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
        } catch (e) { /* almacenamiento no disponible: ignoramos */ }
    }

    /* ---------- Círculo rojo del sidebar ---------- */
    function updateBadge(count) {
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count;
            badge.setAttribute("data-count", String(count));
            badge.removeAttribute("hidden");
        } else {
            badge.setAttribute("hidden", "");
        }
    }

    /* ---------- Creación de toasts ---------- */
    function showToast(title, message, badgeCount) {
        // No apilar demasiados avisos: descartar los más viejos si hace falta.
        while (container.children.length >= MAX_VISIBLE_TOASTS) {
            const oldest = container.firstElementChild;
            if (oldest) dismissToast(oldest);
        }

        const toast = document.createElement("div");
        toast.className = "dispute-toast";
        toast.innerHTML =
            '<div class="dispute-toast-icon"><i class="bi bi-bell-fill"></i></div>' +
            '<div class="dispute-toast-body">' +
                (badgeCount ? '<div class="dispute-toast-title">' + title + ' <span class="dispute-toast-count">' + badgeCount + '</span></div>'
                            : '<div class="dispute-toast-title">' + title + '</div>') +
                '<div class="dispute-toast-message">' + message + '</div>' +
            '</div>' +
            '<button class="dispute-toast-close" title="Cerrar"><i class="bi bi-x-lg"></i></button>';

        // Clic en la tarjeta => bandeja de arbitraje de disputas.
        toast.addEventListener("click", function (e) {
            if (e.target.closest(".dispute-toast-close")) return;
            window.location.href = disputesUrl;
        });

        toast.querySelector(".dispute-toast-close").addEventListener("click", function (e) {
            e.stopPropagation();
            dismissToast(toast);
        });

        container.appendChild(toast);

        // Desaparece solo al cabo de unos segundos.
        setTimeout(() => dismissToast(toast), TOAST_DURATION_MS);
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        toast.addEventListener("animationend", function () {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        });
    }

    /* ---------- Polling y lógica de "novedades nuevas" ---------- */
    let firstFetch = true;

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
            return; // red inestable: lo intentamos en el siguiente ciclo
        }
        if (!data) return;

        const count = data.pending_count || 0;
        const items = data.items || [];
        const ids = items.map(function (i) { return String(i.id); });
        const seen = getSeen();
        const seenSet = new Set(seen);

        updateBadge(count);

        if (firstFetch) {
            firstFetch = false;

            if (isOnDashboard() && count > 0) {
                // Al abrir el dashboard: aviso resumido si hay pendientes.
                const summary = count === 1
                    ? "Tienes 1 novedad pendiente de resolución en la bandeja de arbitraje de disputas."
                    : "Tienes " + count + " novedades pendientes de resolución en la bandeja de arbitraje de disputas.";
                showToast("Novedades pendientes de arbitraje", summary, count);
            }

            // Todo lo que ya estaba pendiente no vuelve a anunciarse.
            setSeen(ids);
            return;
        }

        // Ciclos posteriores: solo avisan las que NO se habían visto antes.
        const newItems = items.filter(function (i) {
            return !seenSet.has(String(i.id));
        });

        if (newItems.length > 0) {
            const merged = Array.from(new Set(seen.concat(ids)));
            setSeen(merged);

            newItems.forEach(function (item) {
                const where = item.origin + " \u2192 " + item.destination;
                showToast(
                    "Nueva novedad \u00b7 Traslado #" + item.id,
                    item.status_label + ": " + where,
                    newItems.length > 1 ? newItems.length : null
                );
            });
        }
    }

    // Arranque casi inmediato y luego cada intervalo.
    setTimeout(poll, 1200);
    setInterval(poll, POLL_INTERVAL_MS);
});
