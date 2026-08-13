console.log("🟢 [inventory_views.js] Archivo JS cargado correctamente.");

// --- ESTADO GLOBAL DE INVENTARIO Y PAGINACIÓN ---
let rawInventoryData = [];      // Datos raw recibidos de la API por la sede activa
let currentPage = 1;            // Página actual
const ITEMS_PER_PAGE = 5;       // Cantidad de insumos por página

document.addEventListener('DOMContentLoaded', () => {
    const appContainer = document.getElementById('inventoryViewApp');
    const baseApiUrl = appContainer ? appContainer.dataset.apiUrl : '/inventory/api/list';
    let currentSelectedLocationId = appContainer ? appContainer.dataset.defaultLocationId : null;

    // 1. FILTRADO EN TIEMPO REAL DE LA LISTA DE SEDES (IZQUIERDA - SOLO ADMIN)
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

    // 2. SELECCIÓN Y CLIC EN LAS SEDES (AJAX)
    const locationListGroup = document.getElementById('locationListGroup');
    if (locationListGroup) {
        locationListGroup.addEventListener('click', (e) => {
            const item = e.target.closest('.location-item');
            if (!item) return;

            console.log("📍 Clic detectado en sede:", item.getAttribute('data-location-name'));

            document.querySelectorAll('#locationListGroup .location-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');

            currentSelectedLocationId = item.getAttribute('data-location-id');
            const locationName = item.getAttribute('data-location-name');

            const titleEl = document.getElementById('currentLocationTitle');
            if (titleEl) {
                titleEl.innerHTML = `<i class="bi bi-box-seam section-title-icon"></i> Mostrando: ${locationName}`;
            }

            // Petición AJAX para refrescar la tabla
            fetchInventoryData(baseApiUrl, currentSelectedLocationId);
        });
    }

    // 3. LISTENERS UNIFICADOS PARA BÚSQUEDA Y FILTRO DE ESTADO
    const productSearchInput = document.getElementById('productSearchInput');
    const stockStatusFilterSelect = document.getElementById('stockStatusFilterSelect');

    if (productSearchInput) {
        productSearchInput.addEventListener('input', () => {
            currentPage = 1; // Resetear a la primera página al buscar
            updateInventoryView();
        });
    }
    if (stockStatusFilterSelect) {
        stockStatusFilterSelect.addEventListener('change', () => {
            currentPage = 1; // Resetear a la primera página al cambiar filtro
            updateInventoryView();
        });
    }

    // 4. LISTENER PARA ENLACE "VER ALERTAS" EN LA TARJETA ROJA
    const btnFilterLowStockCard = document.getElementById('btnFilterLowStockCard');
    if (btnFilterLowStockCard) {
        btnFilterLowStockCard.addEventListener('click', (e) => {
            e.preventDefault();
            if (stockStatusFilterSelect) {
                stockStatusFilterSelect.value = 'low'; // Cambiar filtro a Stock Bajo
                currentPage = 1;
                updateInventoryView(); // Refrescar la vista
            }
        });
    }

    // Carga inicial de inventario si aplica
    if (baseApiUrl && currentSelectedLocationId) {
        fetchInventoryData(baseApiUrl, currentSelectedLocationId);
    }
    // Dentro del event listener DOMContentLoaded:
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
});

/**
 * Petición AJAX al servidor para solicitar los insumos de la sede seleccionada
 */
async function fetchInventoryData(apiUrl, locationId) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.remove('d-none');

    try {
        let url = `${apiUrl}?location_id=${encodeURIComponent(locationId || '')}`;
        console.log("📡 Enviando AJAX a:", url);

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        if (data.success && Array.isArray(data.items)) {
            rawInventoryData = data.items;
        } else {
            rawInventoryData = [];
        }
    } catch (error) {
        console.error('❌ Error cargando los datos de inventario:', error);
        rawInventoryData = [];
    } finally {
        if (overlay) overlay.classList.add('d-none');
        currentPage = 1;
        updateInventoryView();
    }
}
/**
 * Procesa filtros dinámicos, calcula la paginación y actualiza la vista
 */
function updateInventoryView() {
    const searchInput = document.getElementById('productSearchInput');
    const statusSelect = document.getElementById('stockStatusFilterSelect');

    const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const selectedStatus = statusSelect ? statusSelect.value : 'all';

    // 1. Actualizar métricas generales
    updateDashboardCards(rawInventoryData);

    // 2. Filtrar solo insumos con Stock > 0 para el listado activo
    const activeInventory = rawInventoryData.filter(item => {
        const qty = item.current_quantity != null ? Number(item.current_quantity) : 0;
        return qty > 0;
    });

    // 3. Aplicar búsqueda y filtro de estado sobre los productos activos
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

    // 4. Evaluar el motivo si el resultado filtrado está vacío
    let emptySearchReason = null; // 'low_stock_out_of_stock' | 'out_of_stock' | 'not_in_location' | 'generic'

    if (filteredData.length === 0) {
        if (selectedStatus === 'low') {
            // Verificar si existen insumos en stock bajo pero con existencia 0
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
            // Verificar si el producto buscado existe en esta sede pero con Stock = 0
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

    // 5. Actualizar contador superior
    const counter = document.getElementById('itemCounter');
    if (counter) {
        counter.textContent = `${filteredData.length} Insumos`;
    }

    // 6. Cálculo de Paginación
    const totalItems = filteredData.length;
    const totalPages = Math.ceil(totalItems / ITEMS_PER_PAGE);

    if (currentPage > totalPages) currentPage = totalPages || 1;

    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
    const endIndex = Math.min(startIndex + ITEMS_PER_PAGE, totalItems);
    const paginatedItems = filteredData.slice(startIndex, endIndex);

    // 7. Renderizar Filas pasándole el motivo de estado vacío
    renderTableRows(paginatedItems, emptySearchReason);

    // 8. Paginación
    renderPaginationControls(totalPages, totalItems, startIndex + 1, endIndex);
}
/**
 * Renderiza las filas o los estados vacíos personalizados según el contexto
 */
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
                <td data-label="Producto" class="fw-semibold text-dark">${name}</td>
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

/**
 * Controla la visibilidad y botones numéricos de la paginación
 */
function renderPaginationControls(totalPages, totalItems, startItem, endItem) {
    const container = document.getElementById('paginationContainer');
    const paginationList = document.getElementById('paginationList');
    const paginationInfo = document.getElementById('paginationInfo');

    if (!container || !paginationList || !paginationInfo) return;

    // Solo mostrar si hay MÍNIMO 2 PÁGINAS (totalPages > 1)
    if (totalPages <= 1) {
        container.classList.add('d-none');
        return;
    }

    container.classList.remove('d-none');
    paginationInfo.textContent = `Mostrando ${startItem}-${endItem} de ${totalItems} insumos`;

    paginationList.innerHTML = '';

    // Botón Anterior
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

    // Botones de Páginas Numéricas
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

    // Botón Siguiente
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

/*
 * Actualiza la cifra de insumos bajo stock mínimo en la tarjeta superior de métricas
 * (Solo aplica para vistas no administradoras, para evitar pisar el conteo global del Admin)
 */
function updateDashboardCards(inventoryData) {
    const appContainer = document.getElementById('inventoryViewApp');
    const isAdmin = appContainer && appContainer.dataset.isAdmin === 'true';

    // ⛔ Si es Administrador, mantenemos el total global traído por Jinja2 desde la BD
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