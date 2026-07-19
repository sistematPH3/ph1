document.addEventListener("DOMContentLoaded", function() {
    
    // --- FIX RESPONSIVO PARA CONTENEDORES NATIVOS DE BASE_LIST ---
    const iconBox = document.querySelector('.brand-icon-box');
    if (iconBox) {
        const headerContainer = iconBox.closest('.d-flex.justify-content-between');
        if (headerContainer) {
            headerContainer.classList.remove('align-items-center');
            headerContainer.classList.add('flex-column', 'flex-md-row', 'align-items-md-center', 'align-items-start', 'gap-3');
            Array.from(headerContainer.children).forEach(child => {
                child.classList.add('w-100', 'w-md-auto');
            });
        }
    }

    const searchInput = document.getElementById('categorySearchInput');
    if (searchInput) {
        const searchWrapper = searchInput.closest('.d-flex.justify-content-between');
        if (searchWrapper) {
            searchWrapper.classList.remove('align-items-center');
            searchWrapper.classList.add('flex-column', 'flex-md-row', 'gap-3');
            Array.from(searchWrapper.children).forEach(child => {
                child.classList.add('w-100', 'w-md-auto');
            });
        }
    }

    // --- MANEJO DE ALERTAS Y LÓGICA ORIGINAL ---
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            if (window.bootstrap && bootstrap.Alert) {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } else {
                alert.style.transition = "opacity 0.5s ease";
                alert.style.opacity = "0";
                setTimeout(() => alert.remove(), 500);
            }
        }, 2000);
    });

    const controlFilter = document.getElementById('controlTypeFilter');
    const noResultsRow = document.getElementById('noResultsRow');
    
    const desktopRows = document.querySelectorAll('.category-row.d-md-table-row');
    const mobileCards = document.querySelectorAll('.category-row-mobile');

    function executeCombinedFilter() {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedFilter = controlFilter ? controlFilter.value : 'all';
        let totalVisibleDesktop = 0;
        let totalVisibleMobile = 0;

        desktopRows.forEach(row => {
            const categoryName = row.cells[0].textContent.toLowerCase();
            const rowControlType = row.getAttribute('data-control-type');
            
            if (categoryName.includes(query) && (selectedFilter === 'all' || rowControlType === selectedFilter)) {
                row.style.setProperty('display', '', 'important');
                totalVisibleDesktop++;
            } else {
                row.style.setProperty('display', 'none', 'important');
            }
        });

        mobileCards.forEach(card => {
            const categoryName = card.querySelector('h6').textContent.toLowerCase();
            const rowControlType = card.getAttribute('data-control-type');

            if (categoryName.includes(query) && (selectedFilter === 'all' || rowControlType === selectedFilter)) {
                card.style.setProperty('display', 'block', 'important');
                totalVisibleMobile++;
            } else {
                card.style.setProperty('display', 'none', 'important');
            }
        });

        if (noResultsRow) {
            const isMobile = window.innerWidth < 768;
            if (isMobile) {
                noResultsRow.style.setProperty('display', (mobileCards.length > 0 && totalVisibleMobile === 0) ? 'table-row' : 'none', 'important');
            } else {
                noResultsRow.style.setProperty('display', (desktopRows.length > 0 && totalVisibleDesktop === 0) ? 'table-row' : 'none', 'important');
            }
        }
    }

    if (searchInput) searchInput.addEventListener('input', executeCombinedFilter);
    if (controlFilter) controlFilter.addEventListener('change', executeCombinedFilter);
    window.addEventListener('resize', executeCombinedFilter);
});