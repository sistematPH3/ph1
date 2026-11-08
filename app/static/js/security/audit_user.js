document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('genericSearchInput');
    const startDate = document.getElementById('start_date');
    const endDate = document.getElementById('end_date');

    function aplicarFiltros() {
        if (!searchInput) return;

        const filterText = searchInput.value.toLowerCase().trim();
        const desde = startDate ? startDate.value : '';
        const hasta = endDate ? endDate.value : '';

        const tableRows = document.querySelectorAll('tbody tr.audit-data-row');
        const mobileCards = document.querySelectorAll('.mobile-audit-card');
        const noResultsRow = document.getElementById('noResultsRow');
        const emptyRow = document.querySelector('.original-empty-row');

        let visibleRowsCount = 0;
        let visibleCardsCount = 0;

        function coincideFecha(fecha) {
            if (!desde && !hasta) return true;
            if (!fecha) return false;
            if (desde && fecha < desde) return false;
            if (hasta && fecha > hasta) return false;
            return true;
        }

        tableRows.forEach(row => {
            const rowText = row.textContent.toLowerCase();
            const fecha = (row.getAttribute('data-date') || '').slice(0, 10);
            const ok = rowText.includes(filterText) && coincideFecha(fecha);
            row.style.setProperty('display', ok ? '' : 'none', 'important');
            if (ok) visibleRowsCount++;
        });

        mobileCards.forEach(card => {
            const cardText = card.textContent.toLowerCase();
            const fecha = (card.getAttribute('data-date') || '').slice(0, 10);
            const ok = cardText.includes(filterText) && coincideFecha(fecha);
            card.style.setProperty('display', ok ? 'block' : 'none', 'important');
            if (ok) visibleCardsCount++;
        });

        if (noResultsRow) {
            const isMobile = window.innerWidth < 768;

            if (emptyRow && getComputedStyle(emptyRow).display !== 'none' && !filterText && !desde && !hasta) {
                noResultsRow.style.setProperty('display', 'none', 'important');
                return;
            }

            if (isMobile) {
                noResultsRow.style.setProperty('display', (mobileCards.length > 0 && visibleCardsCount === 0) ? 'table-row' : 'none', 'important');
            } else {
                noResultsRow.style.setProperty('display', (tableRows.length > 0 && visibleRowsCount === 0) ? 'table-row' : 'none', 'important');
            }
        }
    }

    if (searchInput) searchInput.addEventListener('keyup', aplicarFiltros);
    if (startDate) startDate.addEventListener('change', aplicarFiltros);
    if (endDate) endDate.addEventListener('change', aplicarFiltros);
});