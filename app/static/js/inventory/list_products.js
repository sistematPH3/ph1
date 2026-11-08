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

    const searchInput = document.getElementById('searchInput');
    const filterGroup = document.querySelector('.mariuska-select-group');

    if (searchInput) {
        const searchWrapper = searchInput.closest('.d-flex.justify-content-between') || searchInput.closest('.d-flex');
        if (searchWrapper) {
            searchWrapper.classList.remove('align-items-center');
            searchWrapper.classList.add('flex-column', 'flex-md-row', 'gap-3', 'w-100'); 
            
            Array.from(searchWrapper.children).forEach(child => {
                child.classList.add('w-100', 'w-md-auto');
            });
        }
    }

    // Buscamos directamente el filtro por su clase para no depender de índices del DOM
    if (filterGroup) {
        filterGroup.classList.add('ms-md-auto');
        
        // Si la herencia de base_list envolvió el bloque en un contenedor div, lo empujamos también
        const filterWrapper = filterGroup.parentElement;
        if (filterWrapper && filterWrapper !== document.body) {
            filterWrapper.classList.add('ms-md-auto', 'w-md-auto');
            filterWrapper.classList.remove('w-100'); 
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

    document.querySelectorAll('.collapse.row-technical-details').forEach(collapseEl => {
        collapseEl.addEventListener('show.bs.collapse', function () {
            this.style.setProperty('display', 'table-row', 'important');
        });
        collapseEl.addEventListener('shown.bs.collapse', function () {
            if (typeof filtrarYPaginarInsumos === 'function') filtrarYPaginarInsumos();
        });
        collapseEl.addEventListener('hidden.bs.collapse', function () {
            if (typeof filtrarYPaginarInsumos === 'function') filtrarYPaginarInsumos();
        });
    });

    document.querySelectorAll('.product-clickable-cell').forEach(cell => {
        cell.addEventListener('click', function(e) {
            if (e.target.closest('input, a, button')) return;

            const row = this.closest('.main-product-row');
            if(!row) return;
            
            const productId = row.getAttribute('data-id');
            const techRow = document.getElementById(`tech-desc-${productId}`);

            if (techRow) {
                if (window.bootstrap && bootstrap.Collapse) {
                    let bsCollapse = bootstrap.Collapse.getInstance(techRow) || new bootstrap.Collapse(techRow, { toggle: false });
                    bsCollapse.toggle();
                } else {
                    techRow.classList.toggle('show');
                    techRow.style.display = techRow.classList.contains('show') ? "table-row" : "none";
                    filtrarYPaginarInsumos();
                }
            }
        });
    });

    const statusSelect = document.getElementById('statusSelect');
    const noResultsRow = document.getElementById('noResultsRow');
    const paginationInfo = document.getElementById('paginationInfo');
    const paginationControls = document.getElementById('paginationControls');
    
    let currentPage = 1;
    const rowsPerPage = 10;

    function filtrarYPaginarInsumos() {
        const searchText = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedStatus = statusSelect ? statusSelect.value : 'all';
        
        const desktopRows = document.querySelectorAll('.main-product-row.d-md-table-row');
        const mobileCards = document.querySelectorAll('.main-product-row-mobile');
        
        let matchingDesktop = [];
        let matchingMobile = [];

        desktopRows.forEach(row => {
            const rowText = row.textContent.toLowerCase();
            const productStatus = row.getAttribute('data-status') || '';

            if (rowText.includes(searchText) && (selectedStatus === 'all' || productStatus === selectedStatus)) {
                matchingDesktop.push(row);
            } else {
                row.style.setProperty('display', 'none', 'important');
                ocultarDetallesTecnicos(row, false);
            }
        });

        mobileCards.forEach(card => {
            const cardText = card.textContent.toLowerCase();
            const productStatus = card.getAttribute('data-status') || '';

            if (cardText.includes(searchText) && (selectedStatus === 'all' || productStatus === selectedStatus)) {
                matchingMobile.push(card);
            } else {
                card.style.setProperty('display', 'none', 'important');
                ocultarDetallesTecnicos(card, true);
            }
        });

        const totalMatching = Math.max(matchingDesktop.length, matchingMobile.length);
        const totalPages = Math.ceil(totalMatching / rowsPerPage) || 1;

        if (currentPage > totalPages) currentPage = totalPages;

        const startIdx = (currentPage - 1) * rowsPerPage;
        const endIdx = startIdx + rowsPerPage;

        matchingDesktop.forEach((row, index) => {
            if (index >= startIdx && index < endIdx) {
                row.style.setProperty('display', '', 'important');
                let nextRow = row.nextElementSibling;
                if (nextRow && nextRow.classList.contains('row-technical-details')) {
                    nextRow.style.setProperty('display', nextRow.classList.contains('show') ? '' : 'none', 'important');
                }
            } else {
                row.style.setProperty('display', 'none', 'important');
                ocultarDetallesTecnicos(row, false);
            }
        });

        matchingMobile.forEach((card, index) => {
            if (index >= startIdx && index < endIdx) {
                card.style.setProperty('display', 'block', 'important');
            } else {
                card.style.setProperty('display', 'none', 'important');
                ocultarDetallesTecnicos(card, true);
            }
        });

        actualizarControlesUI(totalMatching, totalPages, startIdx, endIdx);
    }

    function ocultarDetallesTecnicos(el, isMobile) {
        if (isMobile) {
            const collapseDiv = el.querySelector('.row-technical-details-mobile');
            if (collapseDiv) {
                if (window.bootstrap && bootstrap.Collapse) {
                    let bsCollapse = bootstrap.Collapse.getInstance(collapseDiv);
                    if (bsCollapse) bsCollapse.hide();
                } else {
                    collapseDiv.classList.remove('show');
                }
            }
        } else {
            let nextRow = el.nextElementSibling;
            if (nextRow && nextRow.classList.contains('row-technical-details')) {
                nextRow.style.setProperty('display', 'none', 'important');
                if (window.bootstrap && bootstrap.Collapse) {
                    let bsCollapse = bootstrap.Collapse.getInstance(nextRow);
                    if (bsCollapse) bsCollapse.hide();
                } else {
                    nextRow.classList.remove('show');
                }
            }
        }
    }

    function actualizarControlesUI(totalMatching, totalPages, startIdx, endIdx) {
    const paginationWrapper = document.getElementById('paginationWrapper');
    const paginationRow = paginationWrapper ? paginationWrapper.closest('.generic-pagination-row') : null; // <-- LÍNEA NUEVA
    
    if (totalMatching === 0) {
        if(paginationWrapper) paginationWrapper.style.setProperty('display', 'none', 'important');
        if (noResultsRow) noResultsRow.style.setProperty('display', 'table-row', 'important');
        return;
    }
    if (noResultsRow) noResultsRow.style.setProperty('display', 'none', 'important');

    if (totalPages <= 1) {
        if(paginationWrapper) paginationWrapper.style.setProperty('display', 'none', 'important');
        if(paginationRow) paginationRow.style.setProperty('display', 'none', 'important'); // <-- LÍNEA NUEVA
        return;
    } else {
        if(paginationWrapper) paginationWrapper.style.setProperty('display', 'flex', 'important');
        if(paginationRow) paginationRow.style.setProperty('display', '', 'important'); // <-- LÍNEA NUEVA
    }

        if(paginationInfo && paginationControls) {
            const registroInicial = startIdx + 1;
            const registroFinal = Math.min(endIdx, totalMatching);
            paginationInfo.textContent = `Mostrando registros del ${registroInicial} al ${registroFinal} de un total de ${totalMatching}`;

            let htmlBotones = '';

            htmlBotones += `
                <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                    <a class="page-link border-0 rounded-pill px-3 mx-1 bg-light text-dark shadow-sm" href="#" data-page="${currentPage - 1}">&laquo;</a>
                </li>`;

            for (let i = 1; i <= totalPages; i++) {
                const esActiva = currentPage === i;
                htmlBotones += `
                    <li class="page-item ${esActiva ? 'active' : ''}">
                        <a class="page-link border-0 rounded-pill px-3 mx-1 shadow-sm ${esActiva ? 'bg-mariuska-red text-white fw-bold' : 'bg-light text-dark'}" href="#" data-page="${i}">${i}</a>
                    </li>`;
            }

            htmlBotones += `
                <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                    <a class="page-link border-0 rounded-pill px-3 mx-1 bg-light text-dark shadow-sm" href="#" data-page="${currentPage + 1}">&raquo;</a>
                </li>`;

            paginationControls.innerHTML = htmlBotones;

            paginationControls.querySelectorAll('a').forEach(boton => {
                boton.addEventListener('click', function(e) {
                    e.preventDefault();
                    const paginaDestino = parseInt(this.getAttribute('data-page'));
                    if (paginaDestino && paginaDestino !== currentPage && paginaDestino >= 1 && paginaDestino <= totalPages) {
                        currentPage = paginaDestino;
                        filtrarYPaginarInsumos();
                        window.scrollTo({ top: 0, behavior: 'smooth' });
                    }
                });
            });
        }
    }

    if(searchInput) searchInput.addEventListener('input', () => { currentPage = 1; filtrarYPaginarInsumos(); });
    if(statusSelect) statusSelect.addEventListener('change', () => { currentPage = 1; filtrarYPaginarInsumos(); });
    window.addEventListener('resize', filtrarYPaginarInsumos);

    filtrarYPaginarInsumos();

    document.addEventListener('change', function(e) {
        if (e.target && e.target.classList.contains('toggle-status-switch')) {
            const toggleUrl = e.target.getAttribute('data-url');
            const parentRow = e.target.closest('.main-product-row');
            const parentCard = e.target.closest('.main-product-row-mobile');
            const container = parentRow || parentCard;
            
            if (!container) return;
            
            const productId = container.getAttribute('data-id');
            const desktopRow = document.querySelector(`.main-product-row[data-id="${productId}"]`);
            const mobileCard = document.querySelector(`.main-product-row-mobile[data-id="${productId}"]`);
            const switchDesktop = desktopRow ? desktopRow.querySelector('.toggle-status-switch') : null;
            const switchMobile = mobileCard ? mobileCard.querySelector('.toggle-status-switch') : null;
            
            fetch(toggleUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const updateUI = (el, isMobile) => {
                        if (!el) return;
                        const badgeCell = isMobile ? el.querySelector('.status-badge-cell-mobile') : el.querySelector('.status-badge-cell');
                        if (data.is_active) {
                            el.classList.remove('row-inhabilitada');
                            el.setAttribute('data-status', 'active');
                            if (badgeCell) badgeCell.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge" ${isMobile ? 'style="font-size: 0.75rem;"' : ''}>Operativa</span>`;
                        } else {
                            el.classList.add('row-inhabilitada');
                            el.setAttribute('data-status', 'inactive');
                            if (badgeCell) badgeCell.innerHTML = `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge" ${isMobile ? 'style="font-size: 0.75rem;"' : ''}>Inactiva</span>`;
                        }
                    };

                    updateUI(desktopRow, false);
                    updateUI(mobileCard, true);

                    if (switchDesktop && switchDesktop !== e.target) switchDesktop.checked = e.target.checked;
                    if (switchMobile && switchMobile !== e.target) switchMobile.checked = e.target.checked;

                    filtrarYPaginarInsumos();
                } else {
                    e.target.checked = !e.target.checked;
                    alert("No se pudo cambiar el estado: " + data.error);
                }
            })
            .catch(error => {
                e.target.checked = !e.target.checked;
                console.error("Error en la petición:", error);
                alert("Ocurrió un error de comunicación con el servidor.");
            });
        }
    });
});