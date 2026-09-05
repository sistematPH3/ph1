document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search_query');
    const locationSelect = document.getElementById('location_filter');
    const severitySelect = document.getElementById('severity_filter');
    const startDateInput = document.getElementById('start_date');
    const endDateInput = document.getElementById('end_date');

    // Modales Bootstrap
    const revertModalEl = document.getElementById('revertMermaModal');
    const revertModal = revertModalEl ? new bootstrap.Modal(revertModalEl) : null;

    const successModalEl = document.getElementById('successRevertModal');
    const successModal = successModalEl ? new bootstrap.Modal(successModalEl) : null;

    const revertForm = document.getElementById('revert-merma-form');

    // Definición de función ANTES de ser ejecutada
    const applyFilters = () => {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedLocation = locationSelect ? locationSelect.value.toLowerCase().trim() : '';
        const selectedSeverity = severitySelect ? severitySelect.value : '';
        const startDate = startDateInput ? startDateInput.value : '';
        const endDate = endDateInput ? endDateInput.value : '';

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
                if (detailRow && detailRow.classList.contains('show')) {
                    const bsCollapse = bootstrap.Collapse.getInstance(detailRow);
                    if (bsCollapse) bsCollapse.hide();
                    else detailRow.classList.remove('show');
                }
            }
        });

        const visibleRows = document.querySelectorAll('tr.audit-row:not(.d-none)');
        const noResultsRow = document.getElementById('no-filter-results-row');

        if (noResultsRow) {
            if (visibleRows.length === 0) {
                noResultsRow.classList.remove('d-none');
            } else {
                noResultsRow.classList.add('d-none');
            }
        }
    };

    // Forzar el filtrado inicial al cargar la página
if (locationSelect) {
    applyFilters();
}

    // Escuchar eventos de cambio en los filtros
    if (searchInput) searchInput.addEventListener('input', applyFilters);
    if (locationSelect) locationSelect.addEventListener('change', applyFilters);
    if (severitySelect) severitySelect.addEventListener('change', applyFilters);
    if (startDateInput) startDateInput.addEventListener('change', applyFilters);
    if (endDateInput) endDateInput.addEventListener('change', applyFilters);

    // Delegación global para el botón Revertir
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-revert');
        if (btn) {
            const id = btn.getAttribute('data-id');
            const location = btn.getAttribute('data-location');

            const logIdInput = document.getElementById('revert-log-id');
            const targetIdEl = document.getElementById('revert-target-id');
            const targetLocEl = document.getElementById('revert-target-location');
            const reasonInput = document.getElementById('revert_reason');

            if (logIdInput) logIdInput.value = id;
            if (targetIdEl) targetIdEl.textContent = `#${id}`;
            if (targetLocEl) targetLocEl.textContent = location;
            if (reasonInput) reasonInput.value = '';

            if (revertModal) revertModal.show();
        }
    });

    // Envío del formulario de reversión
    if (revertForm) {
        revertForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const logId = document.getElementById('revert-log-id').value;
            const reason = document.getElementById('revert_reason').value.trim();

            if (reason.length < 15) {
                alert('El motivo debe contener al menos 15 caracteres.');
                return;
            }

            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

            try {
                const response = await fetch(`/waste/merma/api/revert/${logId}`, {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ motivo_reversion: reason })
                });

                const contentType = response.headers.get('content-type');
                let result = {};
                
                if (contentType && contentType.includes('application/json')) {
                    result = await response.json();
                } else {
                    throw new Error(`El servidor devolvió un error HTTP ${response.status}`);
                }

                if (response.ok && result.success) {
                    if (revertModal) revertModal.hide();

                    if (successModal) {
                        const msgEl = document.getElementById('success-revert-message');
                        if (msgEl && result.message) msgEl.textContent = result.message;
                        
                        successModal.show();

                        const btnAccept = document.getElementById('btn-accept-success');
                        if (btnAccept) {
                            btnAccept.addEventListener('click', () => window.location.reload(), { once: true });
                        }
                        if (successModalEl) {
                            successModalEl.addEventListener('hidden.bs.modal', () => window.location.reload(), { once: true });
                        }
                    } else {
                        window.location.reload();
                    }
                } else {
                    const errorMsg = result.errors ? result.errors.join(', ') : (result.message || 'Error desconocido');
                    alert(`No se pudo revertir: ${errorMsg}`);
                }
            } catch (error) {
                console.error('Error detallado:', error);
                alert(`Error al procesar la solicitud: ${error.message}`);
            }
        });
    }
});