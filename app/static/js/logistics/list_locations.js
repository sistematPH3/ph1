// static/js/logistics/list_locations.js

function prepararModal(btn) {
    const id = btn.getAttribute('data-id');
    const nombre = btn.getAttribute('data-name');
    const estaActiva = btn.getAttribute('data-active') === 'true';

    const modal = new bootstrap.Modal(document.getElementById('confirmStatusModal'));
    const bar = document.getElementById('modalAccentBar');
    const iconContainer = document.getElementById('modalIconContainer');
    const title = document.getElementById('modalTitle');
    const message = document.getElementById('modalMessage');
    const confirmBtn = document.getElementById('modalConfirmBtn');
    const form = document.getElementById('confirmStatusForm');
    const inputStatus = document.getElementById('modalCurrentStatus');

    if (estaActiva) {
        bar.style.backgroundColor = "#ee3124";
        iconContainer.innerHTML = '<i class="bi bi-exclamation-octagon-fill text-danger"></i>';
        title.innerText = "¿Desactivar Sede?";
        message.innerHTML = "Estás a punto de desactivar la sede <strong>" + nombre + "</strong>. Si decides desactivar esta sede, los usuarios asignados a ella serán desvinculados.";
        confirmBtn.className = "btn btn-danger btn-lg w-100 mb-2 shadow-sm text-white";
    } else {
        bar.style.backgroundColor = "#198754";
        iconContainer.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
        title.innerText = "¿Activar Sede?";
        message.innerHTML = "Vas a reactivar la sede <strong>" + nombre + "</strong>.";
        confirmBtn.className = "btn btn-success btn-lg w-100 mb-2 shadow-sm text-white";
    }

    form.action = "/sedes/status/" + id;
    inputStatus.value = estaActiva;
    modal.show();
}

function updateFilter(value, text) {
    document.getElementById('statusFilter').value = value;
    document.getElementById('selectedStatusText').innerHTML = `<i class="bi bi-funnel me-2"></i> ${text}`;
    filtrarTabla();
}

function filtrarTabla() {
    let searchText = document.getElementById('searchInput').value.toLowerCase().trim();
    let statusFilter = document.getElementById('statusFilter').value;
    let rows = document.querySelectorAll('.sede-row');
    let visibleCount = 0;

    rows.forEach(row => {
        let nameEl = row.querySelector('.fw-bold');
        let addressEl = row.querySelector('.text-muted.small');
        
        let name = nameEl ? nameEl.textContent.toLowerCase() : "";
        let address = addressEl ? addressEl.textContent.toLowerCase() : "";
        
        let statusPill = row.querySelector('.status-pill');
        let isRowActive = statusPill ? statusPill.classList.contains('active') : false;

        let matchesText = name.includes(searchText) || address.includes(searchText);
        
        let matchesStatus = (statusFilter === "all") || 
                            (statusFilter === "active" && isRowActive) || 
                            (statusFilter === "inactive" && !isRowActive);

        // SOLUCIÓN AL BUG DE RENDERS: Forzar !important inline para ganarle a Bootstrap
        if (matchesText && matchesStatus) {
            row.style.removeProperty('display'); // Remueve el override y deja que actúe el CSS nativo
            visibleCount++;
        } else {
            row.style.setProperty('display', 'none', 'important'); // Oculta con máxima prioridad
        }
    });

    const noResultsRow = document.getElementById('noResultsRow');
    if (noResultsRow) {
        if (visibleCount === 0) {
            noResultsRow.style.removeProperty('display');
        } else {
            noResultsRow.style.setProperty('display', 'none', 'important');
        }
    }
}

// Escuchar eventos en tiempo real garantizando la carga completa del DOM
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        // 'input' es más preciso que 'keyup' para entornos móviles
        searchInput.addEventListener('input', filtrarTabla);
    }
});