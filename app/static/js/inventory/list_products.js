document.addEventListener("DOMContentLoaded", function() {
    // --- MANEJO DE ALERTAS FLASH ---
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

    // --- CORRECCIÓN DE ESTRUCTURA TABULAR PARA FILAS DE DETALLE (ACCORDION) js de list_products---
    document.querySelectorAll('.collapse.row-technical-details').forEach(collapseEl => {
        collapseEl.addEventListener('show.bs.collapse', function () {
            this.style.setProperty('display', 'table-row', 'important');
        });

        collapseEl.addEventListener('shown.bs.collapse', function () {
            if (typeof filtrarYPaginarInsumos === 'function') {
                filtrarYPaginarInsumos();
            }
        });

        collapseEl.addEventListener('hidden.bs.collapse', function () {
            if (typeof filtrarYPaginarInsumos === 'function') {
                filtrarYPaginarInsumos();
            }
        });
    });

    // --- ENRUTAMIENTO DINÁMICO DEL DETALLE TÉCNICO (REEMPLAZO DE DATA-BS ATTRIBUTES) ---
    const clickableCells = document.querySelectorAll('.product-clickable-cell');
    clickableCells.forEach(cell => {
        cell.addEventListener('click', function(e) {
            // No activar el colapso si por error el clic impacta un control directo externo
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return;

            const row = this.closest('.main-product-row');
            const productId = row.getAttribute('data-id');
            const techRow = document.getElementById(`tech-desc-${productId}`);

            if (techRow) {
                if (window.bootstrap && bootstrap.Collapse) {
                    let bsCollapse = bootstrap.Collapse.getInstance(techRow);
                    if (!bsCollapse) {
                        bsCollapse = new bootstrap.Collapse(techRow, { toggle: false });
                    }
                    bsCollapse.toggle();
                } else {
                    // Fallback de contingencia si Bootstrap no inicializa
                    techRow.classList.toggle('show');
                    techRow.style.display = techRow.classList.contains('show') ? "table-row" : "none";
                    filtrarYPaginarInsumos();
                }
            }
        });
    });

    // --- COMPONENTES DE FILTRO Y PAGINACIÓN ---
    const searchInput = document.getElementById('searchInput');
    const statusSelect = document.getElementById('statusSelect');
    const noResultsRow = document.getElementById('noResultsRow');
    const paginationInfo = document.getElementById('paginationInfo');
    const paginationControls = document.getElementById('paginationControls');
    
    let currentPage = 1;
    const rowsPerPage = 10;

    function filtrarYPaginarInsumos() {
        const searchText = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusSelect.value;
        const rows = document.querySelectorAll('.main-product-row');
        
        let matchingRows = [];

        rows.forEach(row => {
            const rowText = row.textContent.toLowerCase();
            const productStatus = row.getAttribute('data-status') || '';

            const coincideTexto = rowText.includes(searchText);
            const coincideEstatus = (selectedStatus === 'all') || (productStatus === selectedStatus);

            if (coincideTexto && coincideEstatus) {
                matchingRows.push(row);
            } else {
                row.style.display = "none";
                ocultarDetallesTecnicos(row);
            }
        });

        const totalMatching = matchingRows.length;
        const totalPages = Math.ceil(totalMatching / rowsPerPage) || 1;

        if (currentPage > totalPages) {
            currentPage = totalPages;
        }

        const startIdx = (currentPage - 1) * rowsPerPage;
        const endIdx = startIdx + rowsPerPage;

        matchingRows.forEach((row, index) => {
            if (index >= startIdx && index < endIdx) {
                row.style.display = "";
                
                let nextRow = row.nextElementSibling;
                if (nextRow && nextRow.classList.contains('row-technical-details')) {
                    nextRow.style.display = nextRow.classList.contains('show') ? "" : "none";
                }
            } else {
                row.style.display = "none";
                ocultarDetallesTecnicos(row);
            }
        });

        actualizarControlesUI(totalMatching, totalPages, startIdx, endIdx);
    }

    function ocultarDetallesTecnicos(mainRow) {
        let nextRow = mainRow.nextElementSibling;
        if (nextRow && nextRow.classList.contains('row-technical-details')) {
            nextRow.style.display = "none";
            if (window.bootstrap && bootstrap.Collapse) {
                let bsCollapse = bootstrap.Collapse.getInstance(nextRow);
                if (bsCollapse) bsCollapse.hide();
            } else {
                nextRow.classList.remove('show');
            }
        }
    }

    function actualizarControlesUI(totalMatching, totalPages, startIdx, endIdx) {
        const paginationWrapper = document.getElementById('paginationWrapper');
        
        if (totalMatching === 0) {
            paginationWrapper.style.setProperty('display', 'none', 'important');
            if (noResultsRow) noResultsRow.style.display = "";
            return;
        }
        if (noResultsRow) noResultsRow.style.display = "none";

        if (totalPages <= 1) {
            paginationWrapper.style.setProperty('display', 'none', 'important');
            return;
        } else {
            paginationWrapper.style.setProperty('display', 'flex', 'important');
        }

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

    searchInput.addEventListener('input', () => { currentPage = 1; filtrarYPaginarInsumos(); });
    statusSelect.addEventListener('change', () => { currentPage = 1; filtrarYPaginarInsumos(); });

    filtrarYPaginarInsumos();

    // --- MANEJO DEL SWITCH ASÍNCRONO DE ESTATUS OPERATIVO ---
    const statusSwitches = document.querySelectorAll('.toggle-status-switch');

    statusSwitches.forEach(switchInput => {
        switchInput.addEventListener('change', function() {
            const toggleUrl = this.getAttribute('data-url');
            const row = this.closest('.main-product-row');
            const badgeCell = row.querySelector('.status-badge-cell');

            fetch(toggleUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.is_active) {
                        row.classList.remove('row-inhabilitada');
                        row.setAttribute('data-status', 'active');
                        badgeCell.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge">Operativa</span>`;
                    } else {
                        row.classList.add('row-inhabilitada');
                        row.setAttribute('data-status', 'inactive');
                        badgeCell.innerHTML = `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle rounded-pill px-3 py-1 font-weight-medium fs-7 status-badge">Inactiva</span>`;
                    }
                    filtrarYPaginarInsumos();
                } else {
                    this.checked = !this.checked;
                    alert("No se pudo cambiar el estado: " + data.error);
                }
            })
            .catch(error => {
                this.checked = !this.checked;
                console.error("Error en la petición:", error);
                alert("Ocurrió un error de comunicación con el servidor.");
            });
        });
    });
});