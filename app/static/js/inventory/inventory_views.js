let rawInventoryData = [];
let currentPage = 1;
const ITEMS_PER_PAGE = 5;

document.addEventListener('DOMContentLoaded', () => {
    const appContainer = document.getElementById('inventoryViewApp');
    const baseApiUrl = appContainer ? appContainer.dataset.apiUrl : '/inventory/api/list';
    let currentSelectedLocationId = appContainer ? appContainer.dataset.defaultLocationId : null;

    ensureLotsModalExists();

    const locationSearchInput = document.getElementById('locationSearchInput');
    if (locationSearchInput) {
        locationSearchInput.addEventListener('input', (e) => {
            const term = e.target.value.toLowerCase().trim();
            const locationItems = document.querySelectorAll('#locationListGroup .location-item');
            
            locationItems.forEach(item => {
                const name = (item.getAttribute('data-location-name') || item.textContent).toLowerCase();
                if (term === '' || name.includes(term)) {
                    item.style.setProperty('display', 'flex', 'important');
                } else {
                    item.style.setProperty('display', 'none', 'important');
                }
            });
        });
    }

    const locationListGroup = document.getElementById('locationListGroup');
    if (locationListGroup) {
        locationListGroup.addEventListener('click', (e) => {
            const item = e.target.closest('.location-item');
            if (!item) return;

            document.querySelectorAll('#locationListGroup .location-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');

            currentSelectedLocationId = item.getAttribute('data-location-id');
            const locationName = item.getAttribute('data-location-name');

            const titleEl = document.getElementById('currentLocationTitle');
            if (titleEl) {
                titleEl.innerHTML = `<i class="bi bi-box-seam section-title-icon"></i> Mostrando: ${locationName}`;
            }

            fetchInventoryData(baseApiUrl, currentSelectedLocationId);
        });
    }

    const productSearchInput = document.getElementById('productSearchInput');
    const stockStatusFilterSelect = document.getElementById('stockStatusFilterSelect');

    if (productSearchInput) {
        productSearchInput.addEventListener('input', () => {
            currentPage = 1;
            updateInventoryView();
        });
    }
    if (stockStatusFilterSelect) {
        stockStatusFilterSelect.addEventListener('change', () => {
            currentPage = 1;
            updateInventoryView();
        });
    }

    const btnFilterLowStockCard = document.getElementById('btnFilterLowStockCard');
    if (btnFilterLowStockCard) {
        btnFilterLowStockCard.addEventListener('click', (e) => {
            e.preventDefault();
            if (stockStatusFilterSelect) {
                stockStatusFilterSelect.value = 'low';
                currentPage = 1;
                updateInventoryView();
            }
        });
    }

    if (baseApiUrl && currentSelectedLocationId) {
        fetchInventoryData(baseApiUrl, currentSelectedLocationId);
    }

    const alertsCollapse = document.getElementById('alertsDetailCollapse');
    const toggleBtnText = document.getElementById('btnToggleAlertsText');
    const toggleBtnIcon = document.getElementById('btnToggleAlertsIcon');

    if (alertsCollapse && toggleBtnText && toggleBtnIcon) {
        alertsCollapse.addEventListener('show.bs.collapse', () => {
            toggleBtnText.textContent = 'Ocultar Alertas';
            toggleBtnIcon.classList.remove('bi-chevron-down');
            toggleBtnIcon.classList.add('bi-chevron-up');
        });

        alertsCollapse.addEventListener('hide.bs.collapse', () => {
            toggleBtnText.textContent = 'Ver Alertas';
            toggleBtnIcon.classList.remove('bi-chevron-up');
            toggleBtnIcon.classList.add('bi-chevron-down');
        });
    }

    const inventoryTableBody = document.getElementById('inventoryTableBody');
    if (inventoryTableBody) {
        inventoryTableBody.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-view-lots');
            if (!btn) return;

            const productId = btn.getAttribute('data-product-id');
            const locationId = btn.getAttribute('data-location-id') || currentSelectedLocationId;
            const productName = btn.getAttribute('data-product-name');
            const sku = btn.getAttribute('data-sku');

            openLotsModal(locationId, productId, productName, sku);
        });
    }
});

function ensureLotsModalExists() {
    if (document.getElementById('inventoryLotsModal')) return;

    const modalHtml = `
        <div class="modal fade" id="inventoryLotsModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered modal-lg">
                <div class="modal-content border-0 shadow-lg" style="border-radius: 20px;">
                    <div class="modal-header bg-light border-bottom-0 py-3 px-4">
                        <div>
                            <h5 class="modal-title fw-bold text-dark m-0" id="lotsModalTitle">
                                <i class="bi bi-layers text-danger me-2"></i>Partidas y Lotes Registrados
                            </h5>
                            <small class="text-muted" id="lotsModalSubtitle"></small>
                        </div>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-4">
                        <div class="table-responsive border rounded-3 overflow-hidden">
                            <table class="table align-middle m-0 custom-insumos-table">
                                <thead>
                                    <tr>
                                        <th class="text-start ps-3">N° de Lote / Partida</th>
                                        <th class="text-center">Vencimiento</th>
                                        <th class="text-center">Existencia Ingresada</th>
                                    </tr>
                                </thead>
                                <tbody id="lotsModalBody">
                                    <tr>
                                        <td colspan="3" class="text-center py-4 text-muted">
                                            <div class="spinner-border spinner-border-sm text-danger me-2" role="status"></div> Consultando lotes...
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="modal-footer border-top-0 pt-0 pe-4 pb-4">
                        <button type="button" class="btn btn-secondary rounded-pill px-4" data-bs-dismiss="modal">Cerrar</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function openLotsModal(locationId, productId, productName, sku) {
    const modalEl = document.getElementById('inventoryLotsModal');
    if (!modalEl) return;

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const subtitleEl = document.getElementById('lotsModalSubtitle');
    const tbody = document.getElementById('lotsModalBody');

    if (subtitleEl) {
        subtitleEl.textContent = `${productName} (${sku})`;
    }

    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="3" class="text-center py-4 text-muted">
                    <div class="spinner-border spinner-border-sm text-danger me-2" role="status"></div> Consultando lotes...
                </td>
            </tr>
        `;
    }

    modal.show();

    try {
        const response = await fetch(`/inventory/api/lots?location_id=${encodeURIComponent(locationId)}&product_id=${encodeURIComponent(productId)}`);
        const result = await response.json();

        if (response.ok && result.success && Array.isArray(result.lots)) {
            if (result.lots.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="3" class="text-center text-muted py-4">
                            <i class="bi bi-info-circle fs-5 d-block mb-1 text-secondary"></i>
                            No hay partidas de lotes individuales registradas para este insumo en esta sede.
                        </td>
                    </tr>
                `;
            } else {
                tbody.innerHTML = result.lots.map(l => `
                    <tr>
                        <td class="ps-3 fw-bold text-dark font-monospace">${l.lot_number}</td>
                        <td class="text-center">
                            <span class="badge bg-warning text-dark border font-monospace">
                                <i class="bi bi-calendar-event me-1"></i>${l.expiration_date}
                            </span>
                        </td>
                        <td class="text-center fw-bold text-primary">${Number(l.quantity).toFixed(2)}</td>
                    </tr>
                `).join('');
            }
        } else {
            throw new Error(result.error || 'Error en la respuesta');
        }
    } catch (e) {
        tbody.innerHTML = `
            <tr>
                <td colspan="3" class="text-center text-danger py-4">
                    <i class="bi bi-exclamation-triangle-fill me-1"></i> No se pudo cargar el desglose de lotes.
                </td>
            </tr>
        `;
    }
}

async function fetchInventoryData(apiUrl, locationId) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.remove('d-none');

    try {
        let url = `${apiUrl}?location_id=${encodeURIComponent(locationId || '')}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        if (data.success && Array.isArray(data.items)) {
            rawInventoryData = data.items;
        } else {
            rawInventoryData = [];
        }
    } catch (error) {
        rawInventoryData = [];
    } finally {
        if (overlay) overlay.classList.add('d-none');
        currentPage = 1;
        updateInventoryView();
    }
}

function updateInventoryView() {
    const searchInput = document.getElementById('productSearchInput');
    const statusSelect = document.getElementById('stockStatusFilterSelect');

    const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const selectedStatus = statusSelect ? statusSelect.value : 'all';

    updateDashboardCards(rawInventoryData);

    const activeInventory = rawInventoryData.filter(item => {
        const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
        return qty > 0;
    });

    const filteredData = activeInventory.filter(item => {
        const sku = (item.sku || item.product?.sku || '').toLowerCase();
        const name = (item.product_name || item.product?.name || '').toLowerCase();
        const matchesSearch = (searchTerm === '' || sku.includes(searchTerm) || name.includes(searchTerm));

        const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
        const minStock = item.min_stock != null ? Number(item.min_stock) : 0;
        const isLow = item.is_low_stock !== undefined ? item.is_low_stock : (qty <= minStock);

        let matchesStatus = true;
        if (selectedStatus === 'low') matchesStatus = isLow;
        if (selectedStatus === 'normal') matchesStatus = !isLow;

        return matchesSearch && matchesStatus;
    });

    let emptySearchReason = null;

    if (filteredData.length === 0) {
        if (selectedStatus === 'low') {
            const zeroStockLowItems = rawInventoryData.filter(item => {
                const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
                const minStock = item.min_stock != null ? Number(item.min_stock) : 0;
                const isLow = item.is_low_stock !== undefined ? item.is_low_stock : (qty <= minStock);
                
                const sku = (item.sku || item.product?.sku || '').toLowerCase();
                const name = (item.product_name || item.product?.name || '').toLowerCase();
                const matchesSearch = (searchTerm === '' || sku.includes(searchTerm) || name.includes(searchTerm));

                return isLow && qty <= 0 && matchesSearch;
            });

            if (zeroStockLowItems.length > 0) {
                emptySearchReason = 'low_stock_out_of_stock';
            }
        } else if (searchTerm !== '') {
            const existsWithZeroStock = rawInventoryData.some(item => {
                const sku = (item.sku || item.product?.sku || '').toLowerCase();
                const name = (item.product_name || item.product?.name || '').toLowerCase();
                const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
                return (sku.includes(searchTerm) || name.includes(searchTerm)) && qty <= 0;
            });

            if (existsWithZeroStock) {
                emptySearchReason = 'out_of_stock';
            } else {
                emptySearchReason = 'not_in_location';
            }
        }
    }

    const counter = document.getElementById('itemCounter');
    if (counter) {
        counter.textContent = `${filteredData.length} Insumos`;
    }

    const totalItems = filteredData.length;
    const totalPages = Math.ceil(totalItems / ITEMS_PER_PAGE);

    if (currentPage > totalPages) currentPage = totalPages || 1;

    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
    const endIndex = Math.min(startIndex + ITEMS_PER_PAGE, totalItems);
    const paginatedItems = filteredData.slice(startIndex, endIndex);

    renderTableRows(paginatedItems, emptySearchReason);
    renderPaginationControls(totalPages, totalItems, startIndex + 1, endIndex);
}

function renderTableRows(items, emptySearchReason = null) {
    const tbody = document.getElementById('inventoryTableBody');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (items.length === 0) {
        if (emptySearchReason === 'low_stock_out_of_stock') {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-5">
                        <i class="bi bi-exclamation-octagon-fill fs-1 d-block mb-2 text-danger"></i>
                        <span class="fw-bold fs-6 text-dark">Los insumos en alerta se encuentran completamente agotados</span><br>
                        <small class="text-muted">Hay insumos bajo el stock mínimo en esta sede, pero su existencia actual es de 0.00 unidades.</small>
                    </td>
                </tr>`;
        } else if (emptySearchReason === 'out_of_stock') {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-5">
                        <i class="bi bi-exclamation-octagon fs-1 d-block mb-2 text-danger"></i>
                        <span class="fw-bold fs-6 text-dark">El producto en stock se ha agotado</span><br>
                        <small class="text-muted">Este producto pertenece a esta sede, pero su existencia actual es 0.00.</small>
                    </td>
                </tr>`;
        } else if (emptySearchReason === 'not_in_location') {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-5">
                        <i class="bi bi-box-seam-fill fs-1 d-block mb-2 text-warning"></i>
                        <span class="fw-bold fs-6 text-dark">Este producto no se encuentra en esta sede</span><br>
                        <small class="text-muted">Verifique la factura de envío o confirme si el insumo fue asignado a otra ubicación.</small>
                    </td>
                </tr>`;
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-muted py-5">
                        <i class="bi bi-funnel fs-1 d-block mb-2 text-secondary"></i>
                        <span class="fw-semibold fs-6 text-dark">No se encontraron insumos para los filtros aplicados.</span><br>
                        <small class="text-muted">Intenta ajustando el texto de búsqueda o el estado de stock.</small>
                    </td>
                </tr>`;
        }
        return;
    }

    tbody.innerHTML = items.map(item => {
        const prodId = item.product_id || '';
        const locId = item.location_id || '';
        const sku = item.sku || item.product?.sku || 'N/A';
        const name = item.product_name || item.product?.name || 'Sin Nombre';
        const locationName = item.location_name || item.location?.name || 'Sede';
        const qty = item.current_quantity != null ? Number(item.current_quantity).toFixed(2) : '0.00';
        const minQty = item.min_stock != null ? Number(item.min_stock).toFixed(2) : '0.00';
        const unit = item.unit || item.product?.unit_of_measure || '';

        const isLow = item.is_low_stock !== undefined 
            ? item.is_low_stock 
            : (Number(qty) <= Number(minQty));

        const badge = isLow 
            ? `<span class="badge bg-danger btn-pill px-2 py-1"><i class="bi bi-exclamation-triangle-fill me-1"></i> Stock Bajo</span>`
            : `<span class="badge bg-success btn-pill px-2 py-1"><i class="bi bi-check-circle-fill me-1"></i> Normal</span>`;

        return `
            <tr>
                <td data-label="SKU" class="fw-bold text-secondary">${sku}</td>
                <td data-label="Producto">
                    <div class="fw-semibold text-dark">${name}</div>
                    <button type="button" class="btn btn-sm btn-link p-0 text-danger text-decoration-none small fw-semibold btn-view-lots d-inline-flex align-items-center gap-1 mt-1" 
                            data-product-id="${prodId}" 
                            data-location-id="${locId}" 
                            data-product-name="${name}" 
                            data-sku="${sku}">
                        <i class="bi bi-layers"></i> Ver Lotes
                    </button>
                </td>
                <td data-label="Ubicación"><span class="badge bg-light text-dark border">${locationName}</span></td>
                <td data-label="Stock Actual" class="text-center fw-bold fs-6">
                    ${qty} <small class="text-muted fs-7">${unit}</small>
                </td>
                <td data-label="Stock Mínimo" class="text-center text-muted">${minQty}</td>
                <td data-label="Estado" class="text-center">${badge}</td>
            </tr>
        `;
    }).join('');
}

function renderPaginationControls(totalPages, totalItems, startItem, endItem) {
    const container = document.getElementById('paginationContainer');
    const paginationList = document.getElementById('paginationList');
    const paginationInfo = document.getElementById('paginationInfo');

    if (!container || !paginationList || !paginationInfo) return;

    if (totalPages <= 1) {
        container.classList.add('d-none');
        return;
    }

    container.classList.remove('d-none');
    paginationInfo.textContent = `Mostrando ${startItem}-${endItem} de ${totalItems} insumos`;

    paginationList.innerHTML = '';

    const prevLi = document.createElement('li');
    prevLi.className = `page-item ${currentPage === 1 ? 'disabled' : ''}`;
    prevLi.innerHTML = `<a class="page-link" href="#"><i class="bi bi-chevron-left"></i></a>`;
    prevLi.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage > 1) {
            currentPage--;
            updateInventoryView();
        }
    });
    paginationList.appendChild(prevLi);

    for (let i = 1; i <= totalPages; i++) {
        const pageLi = document.createElement('li');
        pageLi.className = `page-item ${i === currentPage ? 'active' : ''}`;
        pageLi.innerHTML = `<a class="page-link" href="#">${i}</a>`;
        pageLi.addEventListener('click', (e) => {
            e.preventDefault();
            currentPage = i;
            updateInventoryView();
        });
        paginationList.appendChild(pageLi);
    }

    const nextLi = document.createElement('li');
    nextLi.className = `page-item ${currentPage === totalPages ? 'disabled' : ''}`;
    nextLi.innerHTML = `<a class="page-link" href="#"><i class="bi bi-chevron-right"></i></a>`;
    nextLi.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentPage < totalPages) {
            currentPage++;
            updateInventoryView();
        }
    });
    paginationList.appendChild(nextLi);
}

function updateDashboardCards(inventoryData) {
    const appContainer = document.getElementById('inventoryViewApp');
    const isAdmin = appContainer && appContainer.dataset.isAdmin === 'true';

    if (isAdmin) return;
    if (!Array.isArray(inventoryData)) return;

    const lowStockCount = inventoryData.filter(item => {
        const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
        const minStock = item.min_stock != null ? Number(item.min_stock) : 0;
        return item.is_low_stock !== undefined ? item.is_low_stock : (qty <= minStock);
    }).length;

    const countElement = document.getElementById('cardLowStockCount');
    if (countElement) {
        countElement.textContent = lowStockCount;
    }
}