document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search_query');
    const locationSelect = document.getElementById('location_filter');
    const severitySelect = document.getElementById('severity_filter');
    const startDateInput = document.getElementById('start_date');
    const endDateInput = document.getElementById('end_date');

    const revertModalEl = document.getElementById('revertMermaModal');
    const revertModal = revertModalEl ? new bootstrap.Modal(revertModalEl) : null;
    const revertForm = document.getElementById('revert-merma-form');

    // Filtro ultra-rápido en tiempo real leyendo los atributos data-* del DOM
    const applyFilters = () => {
        const query = searchInput.value.toLowerCase().trim();
        const selectedLocation = locationSelect.value.toLowerCase().trim();
        const selectedSeverity = severitySelect.value;
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        const mainRows = document.querySelectorAll('tr.audit-row');

        mainRows.forEach(row => {
            const logId = row.getAttribute('data-log-id');
            const user = row.getAttribute('data-user') || '';
            const location = row.getAttribute('data-location') || '';
            const severity = row.getAttribute('data-severity') || '';
            const timestamp = row.getAttribute('data-timestamp') || '';
            const products = row.getAttribute('data-products') || '';

            const detailRow = document.querySelector(`tr[data-detail-for="${logId}"]`);

            const matchesQuery = !query || user.includes(query) || location.includes(query) || products.includes(query);
            const matchesLocation = !selectedLocation || location === selectedLocation;
            const matchesSeverity = !selectedSeverity || severity === selectedSeverity;

            let matchesDate = true;
            if (startDate || endDate) {
                if (startDate && timestamp < startDate) matchesDate = false;
                if (endDate && timestamp > endDate) matchesDate = false;
            }

            const isVisible = matchesQuery && matchesLocation && matchesSeverity && matchesDate;

            if (isVisible) {
                row.classList.remove('d-none');
            } else {
                row.classList.add('d-none');
                // Si la fila se oculta y sus detalles estaban desplegados, los replegamos
                if (detailRow && detailRow.classList.contains('show')) {
                    const bsCollapse = bootstrap.Collapse.getInstance(detailRow);
                    if (bsCollapse) bsCollapse.hide();
                    else detailRow.classList.remove('show');
                }
            }
        });
    };

    // Escuchar eventos de entrada y cambio en los filtros
    if (searchInput) searchInput.addEventListener('input', applyFilters);
    if (locationSelect) locationSelect.addEventListener('change', applyFilters);
    if (severitySelect) severitySelect.addEventListener('change', applyFilters);
    if (startDateInput) startDateInput.addEventListener('change', applyFilters);
    if (endDateInput) endDateInput.addEventListener('change', applyFilters);

    // Evento del botón Revertir
    document.querySelectorAll('.btn-revert').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.currentTarget;
            const id = target.getAttribute('data-id');
            const location = target.getAttribute('data-location');

            document.getElementById('revert-log-id').value = id;
            document.getElementById('revert-target-id').textContent = `#${id}`;
            document.getElementById('revert-target-location').textContent = location;
            document.getElementById('revert_reason').value = '';

            if (revertModal) revertModal.show();
        });
    });

    // Procesar formulario de reversión vía AJAX
    if (revertForm) {
        revertForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const logId = document.getElementById('revert-log-id').value;
            const reason = document.getElementById('revert_reason').value.trim();

            if (reason.length < 15) {
                alert('El motivo debe contener al menos 15 caracteres.');
                return;
            }

            try {
                const response = await fetch(`/waste/merma/api/revert/${logId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ motivo_reversion: reason })
                });

                const result = await response.json();
                if (result.success) {
                    if (revertModal) revertModal.hide();
                    // Recargar la página para refrescar el historial renderizado por Jinja2
                    window.location.reload();
                } else {
                    alert('Error: ' + (result.errors || []).join(', '));
                }
            } catch (error) {
                alert('Ocurrió un error al procesar la reversión.');
            }
        });
    }
});