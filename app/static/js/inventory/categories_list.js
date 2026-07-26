document.addEventListener("DOMContentLoaded", function() {
    
    // --- FIX RESPONSIVO PARA ENCABEZADO Y BUSCADOR ---
    const iconBox = document.querySelector('.brand-icon-box');
    if (iconBox) {
        const headerContainer = iconBox.closest('.d-flex.justify-content-between');
        if (headerContainer) {
            headerContainer.classList.remove('align-items-center');
            headerContainer.classList.add('flex-column', 'flex-md-row', 'align-items-md-center', 'align-items-start', 'gap-3');
        }
    }

    const searchInput = document.getElementById('categorySearchInput');
    if (searchInput) {
        const searchWrapper = searchInput.closest('.d-flex.justify-content-between') || searchInput.closest('.d-flex');
        if (searchWrapper) {
            searchWrapper.classList.remove('align-items-center');
            searchWrapper.classList.add('flex-column', 'flex-md-row', 'align-items-md-center', 'gap-2', 'w-100');
        }
    }

    // --- MANEJO DE ALERTAS ---
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
    const statusFilter = document.getElementById('statusFilter');
    const noResultsRow = document.getElementById('noResultsRow');
    
    const desktopRows = document.querySelectorAll('.category-row.d-none.d-md-table-row');
    const mobileCards = document.querySelectorAll('.category-row.d-md-none');

    // --- FILTRADO COMBINADO ---
    function executeCombinedFilter() {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedControl = controlFilter ? controlFilter.value : 'all';
        const selectedStatus = statusFilter ? statusFilter.value : 'all';

        let totalVisibleDesktop = 0;
        let totalVisibleMobile = 0;

        desktopRows.forEach(row => {
            const categoryName = row.cells[0].textContent.toLowerCase();
            const rowControlType = row.getAttribute('data-control-type');
            const rowStatus = row.getAttribute('data-status');

            const matchesSearch = categoryName.includes(query);
            const matchesControl = (selectedControl === 'all' || rowControlType === selectedControl);
            const matchesStatus = (selectedStatus === 'all' || rowStatus === selectedStatus);

            if (matchesSearch && matchesControl && matchesStatus) {
                row.style.removeProperty('display');
                totalVisibleDesktop++;
            } else {
                row.style.setProperty('display', 'none', 'important');
            }
        });

        mobileCards.forEach(card => {
            const categoryNameElement = card.querySelector('h5');
            const categoryName = categoryNameElement ? categoryNameElement.textContent.toLowerCase() : '';
            const rowControlType = card.getAttribute('data-control-type');
            const rowStatus = card.getAttribute('data-status');

            const matchesSearch = categoryName.includes(query);
            const matchesControl = (selectedControl === 'all' || rowControlType === selectedControl);
            const matchesStatus = (selectedStatus === 'all' || rowStatus === selectedStatus);

            if (matchesSearch && matchesControl && matchesStatus) {
                card.style.removeProperty('display');
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
    if (statusFilter) statusFilter.addEventListener('change', executeCombinedFilter);

    // --- DELEGACIÓN GLOBAL AJAX ---
    document.addEventListener('change', async function(e) {
        const switchInput = e.target.closest('.toggle-category-status-switch');
        if (!switchInput) return;

        e.stopPropagation();
        
        const endpointUrl = switchInput.getAttribute('data-url');
        if (!endpointUrl) return;

        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const headers = {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        };
        if (csrfMeta) {
            headers['X-CSRFToken'] = csrfMeta.getAttribute('content');
        }

        try {
            const response = await fetch(endpointUrl, {
                method: 'POST',
                headers: headers
            });

            const data = await response.json();

            if (response.ok && data.success) {
                const isActive = Boolean(data.is_active);

                document.querySelectorAll(`.toggle-category-status-switch[data-url="${endpointUrl}"]`).forEach(sw => {
                    sw.checked = isActive;
                });

                const allCategoryRows = document.querySelectorAll('.category-row');
                allCategoryRows.forEach(rowContainer => {
                    const sw = rowContainer.querySelector(`.toggle-category-status-switch[data-url="${endpointUrl}"]`);
                    if (sw) {
                        const badgeCell = rowContainer.querySelector('.status-badge-cell, .status-badge-cell-mobile');
                        const mobileCardItem = rowContainer.querySelector('.mobile-card-item');

                        rowContainer.setAttribute('data-status', isActive ? 'active' : 'inactive');

                        if (isActive) {
                            rowContainer.classList.remove('row-inhabilitada');
                            if (mobileCardItem) mobileCardItem.classList.remove('row-inhabilitada');

                            if (badgeCell) {
                                badgeCell.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge">Operativa</span>`;
                            }
                        } else {
                            rowContainer.classList.add('row-inhabilitada');
                            if (mobileCardItem) mobileCardItem.classList.add('row-inhabilitada');

                            if (badgeCell) {
                                badgeCell.innerHTML = `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge">Inactiva</span>`;
                            }
                        }
                    }
                });

                executeCombinedFilter();

            } else {
                switchInput.checked = !switchInput.checked;
                alert(data.error || 'No se pudo actualizar el estatus.');
            }
        } catch (error) {
            switchInput.checked = !switchInput.checked;
            console.error('Error al cambiar estatus de la categoría:', error);
        }
    });

    window.addEventListener('resize', executeCombinedFilter);
});