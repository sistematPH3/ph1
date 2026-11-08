document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search_query');
    const locationSelect = document.getElementById('location_filter');
    const severitySelect = document.getElementById('severity_filter');
    const startDateInput = document.getElementById('start_date');
    const endDateInput = document.getElementById('end_date');

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
});