/**
 * movement_audit.js
 * Lógica de la vista de Auditoría Forense de Logística:
 * filtro en vivo del buscador sobre las tarjetas de traslados y bajas.
 */

document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("auditSearchInput");
    if (!searchInput) {
        return;
    }

    searchInput.addEventListener("input", function () {
        const q = this.value.toLowerCase();
        document.querySelectorAll(".ph-audit-card").forEach(function (card) {
            const haystack = card.getAttribute("data-search") || "";
            card.style.display = haystack.toLowerCase().indexOf(q) !== -1 ? "" : "none";
        });
    });
});