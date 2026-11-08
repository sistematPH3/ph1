document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('genericSearchInput');
    
    if (searchInput) {
        searchInput.addEventListener('keyup', function() {
            const filterText = this.value.toLowerCase().trim();
            const tableRows = document.querySelectorAll('tbody tr.audit-data-row');
            const mobileCards = document.querySelectorAll('.mobile-audit-card');
            const noResultsRow = document.getElementById('noResultsRow');
            const emptyRow = document.querySelector('.original-empty-row');
            
            let visibleRowsCount = 0;
            let visibleCardsCount = 0;
            
            tableRows.forEach(row => {
                const rowText = row.textContent.toLowerCase();
                if (rowText.includes(filterText)) {
                    row.style.setProperty('display', '', 'important');
                    visibleRowsCount++;
                } else {
                    row.style.setProperty('display', 'none', 'important');
                }
            });

            mobileCards.forEach(card => {
                const cardText = card.textContent.toLowerCase();
                if (cardText.includes(filterText)) {
                    card.style.setProperty('display', 'block', 'important');
                    visibleCardsCount++;
                } else {
                    card.style.setProperty('display', 'none', 'important');
                }
            });

            if (noResultsRow) {
                const isMobile = window.innerWidth < 768;
                
                if (emptyRow && getComputedStyle(emptyRow).display !== 'none' && !filterText) {
                    noResultsRow.style.setProperty('display', 'none', 'important');
                    return;
                }

                if (isMobile) {
                    noResultsRow.style.setProperty('display', (mobileCards.length > 0 && visibleCardsCount === 0) ? 'table-row' : 'none', 'important');
                } else {
                    noResultsRow.style.setProperty('display', (tableRows.length > 0 && visibleRowsCount === 0) ? 'table-row' : 'none', 'important');
                }
            }
        });
    }
});