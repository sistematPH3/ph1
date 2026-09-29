let currentCurrency = "USD";

function generateRowId() {
    return 'new_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 5);
}

const today = new Date();
const fmtFechaLocal = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const formattedToday = fmtFechaLocal(today);
const tenYearsAgo = new Date();
tenYearsAgo.setFullYear(today.getFullYear() - 10);
const formattedTenYearsAgo = fmtFechaLocal(tenYearsAgo);

const dateFilterInput = document.getElementById('date-filter');
if (dateFilterInput) {
    dateFilterInput.max = formattedToday;
    dateFilterInput.min = formattedTenYearsAgo;
}

const searchInput = document.getElementById('search-input');
const supplierFilter = document.getElementById('supplier-filter');
const tableRows = Array.from(document.querySelectorAll('.purchase-row'));
const mobileCards = Array.from(document.querySelectorAll('.mobile-purchase-card'));
const noDataRow = document.getElementById('no-data-row');
const paginationBox = document.getElementById('pagination-box');
const paginationItems = document.getElementById('pagination-items');

let filteredRows = [...tableRows];
let filteredCards = [...mobileCards];
let currentPage = 1;
const rowsPerPage = 10;

function filterAndPaginate() {
    const searchText = searchInput ? searchInput.value.toLowerCase().trim() : '';
    const selectedSupplier = supplierFilter ? supplierFilter.value.toLowerCase().trim() : ''; 
    const selectedDate = dateFilterInput ? dateFilterInput.value : ''; 

    document.querySelectorAll('.detail-row-container.show').forEach(row => {
        const bsCollapse = bootstrap.Collapse.getInstance(row);
        if (bsCollapse) bsCollapse.hide();
    });

    const cleanSearchText = searchText.replace('#', '');

    const isMatch = (el) => {
        const id = el.getAttribute('data-id').toLowerCase().trim();
        const supplier = el.getAttribute('data-supplier').toLowerCase().trim(); 
        const date = el.getAttribute('data-date'); 

        const matchesSearch = !cleanSearchText || id.includes(cleanSearchText) || supplier.includes(cleanSearchText);
        const matchesSupplier = !selectedSupplier || supplier === selectedSupplier; 
        const matchesDate = !selectedDate || date === selectedDate;

        return matchesSearch && matchesSupplier && matchesDate;
    };

    filteredRows = tableRows.filter(isMatch);
    filteredCards = mobileCards.filter(isMatch);

    if (filteredRows.length === 0 && filteredCards.length === 0) {
        tableRows.forEach(row => row.style.setProperty('display', 'none', 'important'));
        mobileCards.forEach(card => card.style.setProperty('display', 'none', 'important'));
        document.querySelectorAll('.detail-row-container').forEach(row => row.classList.remove('show'));
        if (noDataRow) noDataRow.classList.remove('d-none');
        if (paginationBox) {
            paginationBox.classList.add('d-none');
            paginationItems.innerHTML = '';
        }
        return;
    } else {
        if (noDataRow) noDataRow.classList.add('d-none');
        if (paginationBox) paginationBox.classList.remove('d-none');
    }

    currentPage = 1;
    renderTable();
}

function renderTable() {
    tableRows.forEach(row => row.style.setProperty('display', 'none', 'important'));
    mobileCards.forEach(card => card.style.setProperty('display', 'none', 'important'));

    const startIndex = (currentPage - 1) * rowsPerPage;
    const endIndex = startIndex + rowsPerPage;
    
    filteredRows.slice(startIndex, endIndex).forEach(row => row.style.setProperty('display', 'table-row', 'important'));
    filteredCards.slice(startIndex, endIndex).forEach(card => card.style.setProperty('display', 'block', 'important'));

    renderPagination();
}

function renderPagination() {
    if (!paginationItems) return;
    paginationItems.innerHTML = '';
    const totalItems = Math.max(filteredRows.length, filteredCards.length);
    const totalPages = Math.ceil(totalItems / rowsPerPage);
    
    if (totalPages <= 1) {
        if (paginationBox) paginationBox.classList.add('d-none');
        return;
    }
    if (paginationBox) paginationBox.classList.remove('d-none');

    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement('li');
        li.className = `page-item ${i === currentPage ? 'active' : ''}`;
        li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
        li.addEventListener('click', (e) => {
            e.preventDefault();
            currentPage = i;
            renderTable();
        });
        paginationItems.appendChild(li);
    }
}

document.querySelectorAll('.detail-row-container').forEach(detailRow => {
    detailRow.addEventListener('show.bs.collapse', function () {
        const purchaseId = this.getAttribute('data-purchase-id');
        loadCollapseDetails(purchaseId);
    });
});

if (searchInput) searchInput.addEventListener('input', filterAndPaginate);
if (supplierFilter) supplierFilter.addEventListener('change', filterAndPaginate);
if (dateFilterInput) dateFilterInput.addEventListener('change', filterAndPaginate);

filterAndPaginate();

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

function loadCollapseDetails(purchaseId) {
    const tbodies = document.querySelectorAll(`.collapse-body-${purchaseId}`);
    if (tbodies.length === 0) return;
    
    if (tbodies[0].children.length > 1 || (tbodies[0].children.length === 1 && !tbodies[0].children[0].innerHTML.includes('Cargando'))) {
        return;
    }

    fetch(`/logistics/purchases/management/${purchaseId}/details`)
        .then(response => {
            if (!response.ok) throw new Error('No se pudo procesar el desglose.');
            return response.json();
        })
        .then(data => {
            tbodies.forEach(tbody => {
                tbody.innerHTML = '';
                if(data.details.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-3">No hay insumos registrados en esta compra.</td></tr>`;
                    return;
                }

                const isMobile = tbody.closest('.mobile-purchase-card') !== null;

                data.details.forEach(detail => {
                    const formattedForeignPrice = Number(detail.foreign_price || 0).toLocaleString('es-VE', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    // subtotal_bs llega null cuando la factura no tiene tasa:
                    // se muestra "—" en vez de 0,00, que parecía una compra gratis.
                    const formattedSubtotalBs = (detail.subtotal_bs === null || detail.subtotal_bs === undefined)
                        ? '—'
                        : Number(detail.subtotal_bs).toLocaleString('es-VE', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    const expDateBadge = detail.expiration_date ? `<span class="badge bg-warning text-dark border"><i class="bi bi-calendar-event me-1"></i>${escapeHtml(detail.expiration_date.split('-').reverse().join('/'))}</span>` : `<span class="text-muted small">N/A</span>`;
                    const lotBadge = `<span class="badge bg-light text-dark border font-monospace">${escapeHtml(detail.lot_number || 'N/A')}</span>`;
                    const skuEscaped = escapeHtml(detail.product_sku);
                    
                    let rowHtml = "";
                    if (isMobile) {
                        rowHtml = `
                            <tr>
                                <td class="p-2">
                                    <div class="d-flex justify-content-between mb-1">
                                        <span class="fw-bold text-dark small">${skuEscaped}</span>
                                        <span class="text-secondary small fw-bold">#${escapeHtml(detail.id)}</span>
                                    </div>
                                    <div class="d-flex justify-content-between align-items-center mb-1">
                                        <span class="small text-muted">Lote: ${lotBadge}</span>
                                        <span class="small text-muted">Cant: <strong class="text-primary">${escapeHtml(detail.quantity)}</strong></span>
                                    </div>
                                    <div class="d-flex justify-content-between align-items-center mb-1">
                                        <span class="small text-muted">Vence:</span>
                                        ${expDateBadge}
                                    </div>
                                    <div class="d-flex justify-content-between align-items-center mt-2 border-top pt-2">
                                        <span class="text-success small fw-semibold">${escapeHtml(data.currency)} ${formattedForeignPrice}</span>
                                        <span class="fw-bold text-dark small">Bs. ${formattedSubtotalBs}</span>
                                    </div>
                                </td>
                            </tr>
                        `;
                    } else {
                        rowHtml = `
                            <tr>
                                <td class="text-secondary fw-bold">#${escapeHtml(detail.id)}</td>
                                <td><span class="badge bg-dark text-white">${skuEscaped}</span></td>
                                <td class="text-center fw-bold text-primary">${escapeHtml(detail.quantity)}</td>
                                <td class="text-center">${lotBadge}</td>
                                <td class="text-center">${expDateBadge}</td>
                                <td class="text-end text-success fw-semibold">${escapeHtml(data.currency)} ${formattedForeignPrice}</td>
                                <td class="text-end fw-bold text-dark">Bs. ${formattedSubtotalBs}</td>
                            </tr>
                        `;
                    }
                    tbody.insertAdjacentHTML('beforeend', rowHtml);
                });
            });
        })
        .catch(error => {
            tbodies.forEach(tbody => {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-3"><i class="bi bi-exclamation-triangle-fill"></i> Error: ${escapeHtml(error.message)}</td></tr>`;
            });
        });
}

const modalAnnulElement = document.getElementById('modalAnnul');
let modalAnnul = null;
if (modalAnnulElement) {
    modalAnnul = new bootstrap.Modal(modalAnnulElement);
}
const annulPurchaseIdSpan = document.getElementById('annulPurchaseId');
const formAnnulConfirm = document.getElementById('formAnnulConfirm');
const annulErrorAlert = document.getElementById('annulErrorAlert');
const btnAnnulConfirm = document.getElementById('btnAnnulConfirm');

// Sin este intercept el <form method="POST"> navegaba al endpoint, que devuelve
// JSON: el usuario se quedaba mirando la respuesta cruda en el navegador.
if (formAnnulConfirm) {
    formAnnulConfirm.addEventListener('submit', function(e) {
        e.preventDefault();
        const url = formAnnulConfirm.getAttribute('action');
        if (!url) return;

        const mensaje = (texto, esError) => {
            if (!annulErrorAlert) { window.alert(texto); return; }
            annulErrorAlert.innerHTML = (esError
                ? '<i class="bi bi-exclamation-triangle-fill me-2"></i>'
                : '<i class="bi bi-check-circle-fill me-2"></i>') + escapeHtml(texto);
            annulErrorAlert.classList.remove('d-none');
        };

        if (btnAnnulConfirm) {
            btnAnnulConfirm.disabled = true;
            btnAnnulConfirm.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Procesando...';
        }
        if (annulErrorAlert) annulErrorAlert.classList.add('d-none');

        fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
            .then(res => res.json().then(body => ({ status: res.status, body })))
            .then(({ status, body }) => {
                if (body && body.success) {
                    if (modalAnnul) modalAnnul.hide();
                    window.location.reload();
                    return;
                }
                if (status === 401) return mensaje('Tu sesión expiró. Vuelve a iniciar sesión.', true);
                mensaje((body && body.error) || 'No se pudo anular la compra.', true);
            })
            .catch(() => mensaje('No se pudo procesar la solicitud. Revisa tu conexión.', true))
            .finally(() => {
                if (btnAnnulConfirm) {
                    btnAnnulConfirm.disabled = false;
                    btnAnnulConfirm.innerHTML = 'Confirmar';
                }
            });
    });
}

const modalEditElement = document.getElementById('modalEdit');
let modalEdit = null;
if (modalEditElement) {
    modalEdit = new bootstrap.Modal(modalEditElement);
    modalEditElement.addEventListener('hidden.bs.modal', function() {
        if (window._editCountdownInterval) {
            clearInterval(window._editCountdownInterval);
            window._editCountdownInterval = null;
        }
        const timeLimitEl = document.getElementById('editTimeLimit');
        if (timeLimitEl) timeLimitEl.classList.add('d-none');
    });
}
const editPurchaseIdSpan = document.getElementById('editPurchaseId');
const editTableBody = document.getElementById('edit-table-body');
const btnSaveEdit = document.getElementById('btnSaveEdit');
const editErrorAlert = document.getElementById('editErrorAlert');
const editReasonInput = document.getElementById('editReason');
const editCurrencyLabel = document.getElementById('editCurrencyLabel');
let currentEditPurchaseId = null;

// Cuenta regresiva de la ventana de edición. El plazo lo calcula el servidor
// (remaining_seconds): antes se derivaba de data-purchase-date, una fecha naive
// sin zona que el navegador interpretaba en su huso local.
function setupEditCountdown(remainingSeconds) {
    const timeLimitEl = document.getElementById('editTimeLimit');
    const timeLimitTextEl = document.getElementById('editTimeLimitText');
    if (!timeLimitEl || !timeLimitTextEl) return;

    if (window._editCountdownInterval) {
        clearInterval(window._editCountdownInterval);
        window._editCountdownInterval = null;
    }

    if (typeof remainingSeconds !== 'number' || remainingSeconds <= 0) {
        timeLimitEl.classList.add('d-none');
        return;
    }

    let restante = remainingSeconds;
    const pintar = () => {
        if (restante <= 0) {
            timeLimitTextEl.textContent = 'Tiempo expirado';
            timeLimitEl.className = 'badge rounded-pill px-3 py-2 small d-inline-block';
            timeLimitEl.style.backgroundColor = '#f8d7da';
            timeLimitEl.style.color = '#842029';
            timeLimitEl.style.borderColor = '#f5c6cb';
            if (window._editCountdownInterval) clearInterval(window._editCountdownInterval);
            return;
        }
        const dias = Math.floor(restante / 86400);
        const horas = Math.floor((restante % 86400) / 3600);
        const mins = Math.floor((restante % 3600) / 60);
        const segs = restante % 60;
        let txt = '';
        if (dias > 0) txt += `${dias}d `;
        if (horas > 0 || dias > 0) txt += `${horas}h `;
        txt += `${mins}m ${String(segs).padStart(2, '0')}s`;
        timeLimitTextEl.textContent = `Tiempo restante: ${txt}`;
        restante -= 1;
    };

    pintar();
    timeLimitEl.classList.remove('d-none');
    window._editCountdownInterval = setInterval(pintar, 1000);
}

const handleActionClick = function(e) {
    const triggerAnnulButton = e.target.closest('.btn-annul-trigger');
    if (triggerAnnulButton && modalAnnul) {
        const purchaseId = triggerAnnulButton.getAttribute('data-id');
        const annulUrl = triggerAnnulButton.getAttribute('data-url');
        if (annulPurchaseIdSpan) annulPurchaseIdSpan.innerText = `#${purchaseId}`;
        if (formAnnulConfirm) formAnnulConfirm.setAttribute('action', annulUrl);
        if (annulErrorAlert) annulErrorAlert.classList.add('d-none');
        modalAnnul.show();
    }

    const triggerEditButton = e.target.closest('.btn-edit-trigger');
    if (triggerEditButton && modalEdit && editTableBody) {
        const purchaseId = triggerEditButton.getAttribute('data-id');
        currentEditPurchaseId = purchaseId;
        if (editPurchaseIdSpan) editPurchaseIdSpan.innerText = purchaseId;

        if (editErrorAlert) editErrorAlert.classList.add('d-none');
        if (editReasonInput) editReasonInput.value = '';
        editTableBody.innerHTML = `<tr><td colspan="6" class="text-center py-5"><div class="spinner-border text-danger" role="status"></div></td></tr>`;
        modalEdit.show();

        fetch(`/logistics/purchases/management/${purchaseId}/details`)
            .then(res => {
                if (res.status === 401) throw new Error('Tu sesión expiró. Vuelve a iniciar sesión.');
                if (res.status === 403) throw new Error('No tienes permisos para modificar compras.');
                if (!res.ok) throw new Error('No se pudo cargar el detalle de la compra.');
                return res.json();
            })
            .then(data => {
                if (data.error) throw new Error(data.error);
                loadEditTable(data);
                setupEditCountdown(data.remaining_seconds);
                if (btnSaveEdit) btnSaveEdit.disabled = !data.can_modify;
            })
            .catch(err => {
                editTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-4"><i class="bi bi-exclamation-triangle-fill me-2"></i>${escapeHtml(err.message || 'Error desconocido.')}</td></tr>`;
            });
    }
};

// Carga los renglones en la tabla del modal de edición.
function loadEditTable(data) {
    if (!editTableBody) return;
    editTableBody.innerHTML = '';
    currentCurrency = data.currency;
    // La moneda se anuncia UNA sola vez, en el encabezado de la columna.
    // Antes se repetia dentro de cada celda con un input-group, que ademas
    // desbordaba la columna y partia el input en dos lineas.
    if (editCurrencyLabel) editCurrencyLabel.textContent = data.currency || 'Moneda';
    
    if (!data.details || data.details.length === 0) {
        editTableBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No hay insumos editables.</td></tr>`;
        return;
    }
    data.details.forEach(item => {
        const tr = document.createElement('tr');
        // normalizarNumeroEdit devuelve NaN si el valor no es parseable, y
        // NaN.toFixed(2) pintaba literalmente "NaN" en el campo de precio.
        const precioNum = normalizarNumeroEdit(item.foreign_price);
        const precioTexto = (isNaN(precioNum) ? '0.00' : precioNum.toFixed(2));
        tr.innerHTML = `
            <td class="ps-3 pe-3">
                <div class="text-end text-md-start">
                    <span class="badge bg-secondary mb-1">${escapeHtml(item.product_sku)}</span><br>
                    <small class="text-muted">Registro #${escapeHtml(item.id)}</small>
                </div>
            </td>
            <td class="text-center px-2">
                <input type="text" inputmode="decimal" class="form-control text-center edit-qty fw-bold text-dark border-secondary" data-id="${escapeHtml(item.id)}" value="${escapeHtml(item.quantity)}" placeholder="0.00">
            </td>
            <td class="text-center px-2">
                <input type="text" class="form-control text-start edit-lot border-secondary text-dark px-2 font-monospace" data-id="${escapeHtml(item.id)}" value="${escapeHtml(item.lot_number === 'N/A' ? '' : item.lot_number)}" placeholder="Opcional">
            </td>
            <td class="text-center px-2">
                <input type="date" class="form-control text-center edit-exp border-secondary text-dark px-1" value="${escapeHtml(item.expiration_date || '')}">
            </td>
            <td class="px-2" data-currency="${escapeHtml(data.currency)}">
                <input type="text" inputmode="decimal" class="form-control text-end edit-price border-secondary ps-2 text-dark" data-id="${escapeHtml(item.id)}" value="${escapeHtml(precioTexto)}" placeholder="0.00">
            </td>
            <td class="text-center px-1 align-middle">
                <button type="button" class="btn btn-sm btn-outline-danger remove-edit-row" data-id="${escapeHtml(item.id)}" title="Eliminar insumo">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
        editTableBody.appendChild(tr);
    });
}

const mainContainer = document.getElementById('purchases-main-container');
if (mainContainer) {
    mainContainer.addEventListener('click', handleActionClick);
}

const btnAddRowEdit = document.getElementById('btnAddRowEdit');
if (btnAddRowEdit) {
    btnAddRowEdit.addEventListener('click', function() {
        const templateEl = document.getElementById('new-product-options');
        const optionsHtml = templateEl ? templateEl.innerHTML : '<option value="" disabled selected>Seleccione...</option>';
        const newRowId = generateRowId();

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="ps-3 pe-3">
                <div class="text-end text-md-start">
                    <select class="form-select form-select-sm edit-prod-id border-success text-dark fw-bold mb-1 w-100" data-id="${newRowId}">
                        ${optionsHtml}
                    </select>
                    <small class="text-success fw-bold"><i class="bi bi-star-fill"></i> ANEXO</small>
                </div>
            </td>
            <td class="text-center px-2">
                <input type="text" inputmode="decimal" class="form-control text-center edit-qty fw-bold text-dark border-success" data-id="${newRowId}" value="1" placeholder="0.00">
            </td>
            <td class="text-center px-2">
                <input type="text" class="form-control text-start edit-lot border-success text-dark px-2 font-monospace" data-id="${newRowId}" value="" placeholder="Opcional / Auto">
            </td>
            <td class="text-center px-2">
                <input type="date" class="form-control text-center edit-exp border-success text-dark px-1" value="">
            </td>
            <td class="px-2" data-currency="${escapeHtml(currentCurrency)}">
                <input type="text" inputmode="decimal" class="form-control text-end edit-price border-success text-dark" data-id="${newRowId}" value="" placeholder="0.00">
            </td>
            <td class="text-center px-1 align-middle">
                <button type="button" class="btn btn-sm btn-outline-danger remove-edit-row" title="Quitar fila">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
        if (editTableBody) editTableBody.appendChild(tr);
    });
}

if (editTableBody) {
    editTableBody.addEventListener('click', function(e) {
        const btn = e.target.closest('.remove-edit-row');
        if (!btn) return;
        const row = btn.closest('tr');
        if (row) row.remove();
    });
}

function normalizarNumeroEdit(value) {
    if (typeof value === 'number') return value;
    if (typeof value !== 'string') return NaN;
    let s = String(value).trim().replace(/\s+/g, '');
    if (!s) return NaN;
    let sign = '';
    if (s[0] === '-') { sign = '-'; s = s.slice(1); }
    let norm;
    if (s.indexOf(',') !== -1) {
        norm = s.replace(/\./g, '').replace(',', '.');
    } else if (/^0+\.\d+$/.test(s)) {
        // Un punto tras un "0" inicial es decimal, no separador de miles:
        // "0.500" es medio, no 500. Debe coincidir con normalizar_numero()
        // del servidor para que lo que ve el usuario sea lo que se guarda.
        norm = s;
    } else {
        norm = s.replace(/\.(?=\d{3}(?!\d))/g, '');
    }
    return parseFloat(sign + norm);
}

function parseNumEdit(value) {
    return normalizarNumeroEdit(value);
}

if (btnSaveEdit) {
    btnSaveEdit.addEventListener('click', function() {
        if (editErrorAlert) editErrorAlert.classList.add('d-none');
        
        const reasonVal = editReasonInput ? editReasonInput.value.trim() : '';
        if (!reasonVal || reasonVal.length < 5) {
            if (editErrorAlert) {
                editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>Debe ingresar un motivo válido para la modificación (mínimo 5 caracteres).';
                editErrorAlert.classList.remove('d-none');
            }
            return;
        }

        const items = [];
        const rows = editTableBody ? editTableBody.querySelectorAll('tr') : [];
        let formValid = true;
        
        rows.forEach(row => {
            const qtyInput = row.querySelector('.edit-qty');
            const priceInput = row.querySelector('.edit-price');
            const expInput = row.querySelector('.edit-exp');
            const lotInput = row.querySelector('.edit-lot');
            const prodSelect = row.querySelector('.edit-prod-id');
            
            if(qtyInput && priceInput) {
                const rowId = qtyInput.getAttribute('data-id');
                const qtyVal = parseNumEdit(qtyInput.value);
                const priceVal = parseNumEdit(priceInput.value);
                const lotVal = lotInput ? lotInput.value.trim() : "";

                let qtyValid = qtyInput.value !== '' && !isNaN(qtyVal) && qtyVal >= 0.01 && qtyVal <= 999999.99;
                let priceValid = priceInput.value !== '' && !isNaN(priceVal) && priceVal >= 0.01 && priceVal <= 9999999.99;
                if (!qtyValid) qtyInput.classList.add('is-invalid');
                else qtyInput.classList.remove('is-invalid');
                if (!priceValid) priceInput.classList.add('is-invalid');
                else priceInput.classList.remove('is-invalid');

                let prodValid = true;
                if (rowId.startsWith('new_')) {
                    prodValid = !!(prodSelect && prodSelect.value);
                    if (!prodValid) prodSelect.classList.add('is-invalid');
                    else prodSelect.classList.remove('is-invalid');
                }
                if (!qtyValid || !priceValid || !prodValid) {
                    formValid = false;
                    return;
                }

                if (rowId.startsWith('new_')) {
                    items.push({
                        id: rowId,
                        product_id: parseInt(prodSelect.value),
                        quantity: qtyVal,
                        foreign_price: priceVal,
                        expiration_date: expInput ? expInput.value : "",
                        lot_number: lotVal
                    });
                } else {
                    items.push({
                        id: rowId,
                        quantity: qtyVal,
                        foreign_price: priceVal,
                        expiration_date: expInput ? expInput.value : "",
                        lot_number: lotVal
                    });
                }
            }
        });

        if (!formValid) {
            if (editErrorAlert) {
                editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>Corrige los campos marcados: la cantidad y el precio deben ser mayor o igual a 0.01, y los nuevos insumos deben tener un producto seleccionado.';
                editErrorAlert.classList.remove('d-none');
            }
            return;
        }

        // No se puede dejar la compra sin renglones. Antes el guardado se
        // salía en silencio si el usuario borraba todas las filas.
        if (items.length === 0) {
            if (editErrorAlert) {
                editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>La compra debe conservar al menos un insumo. Si quieres anularla por completo, usa el botón de anular.';
                editErrorAlert.classList.remove('d-none');
            }
            return;
        }

        btnSaveEdit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Procesando...';
        btnSaveEdit.disabled = true;

        fetch(`/logistics/purchases/management/${currentEditPurchaseId}/edit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: items, reason: reasonVal })
        })
        .then(res => res.json().then(body => ({ status: res.status, body })))
        .then(({ status, body }) => {
            if (body && body.success) {
                window.location.reload();
                return;
            }
            // El backend devuelve 'error' (resumen) y 'details' (campo a campo).
            // Antes solo se pintaba 'error' con innerHTML y sin escapar: los
            // mensajes de ValueError incluyen el nombre del producto, así que
            // un nombre con HTML se ejecutaba en el navegador del admin. Ahora
            // se escapa y además se listan los errores por campo.
            if (editErrorAlert) {
                let texto = (body && body.error) || 'No se pudo editar la compra.';
                if (status === 401) {
                    texto = 'Tu sesión expiró. Vuelve a iniciar sesión.';
                }
                const detalles = body && body.details ? Object.values(body.details) : [];
                if (detalles.length > 0) {
                    const lista = detalles
                        .filter(d => d !== null && d !== undefined && String(d).trim() !== '')
                        .map(d => `<li>${escapeHtml(String(d).trim())}</li>`)
                        .join('');
                    if (lista) {
                        texto += `<ul style="margin:0.5rem 0 0 0; padding-left:1.25rem; text-align:left">${lista}</ul>`;
                    }
                }
                editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>' + texto;
                editErrorAlert.classList.remove('d-none');
            }
            btnSaveEdit.innerHTML = '<i class="bi bi-floppy me-1"></i> Guardar Cambios';
            btnSaveEdit.disabled = false;
        })
        .catch(err => {
            if (editErrorAlert) {
                editErrorAlert.innerHTML = '<i class="bi bi-wifi-off me-2"></i>Fallo crítico de conexión al servidor.';
                editErrorAlert.classList.remove('d-none');
            }
            btnSaveEdit.innerHTML = '<i class="bi bi-floppy me-1"></i> Guardar Cambios';
            btnSaveEdit.disabled = false;
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const exportButtons = document.querySelectorAll('[data-export-listado]');
    const searchInputEl = document.getElementById('search-input');
    const supplierFilterEl = document.getElementById('supplier-filter');
    const dateFilterEl = document.getElementById('date-filter');

    exportButtons.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            const base = btn.getAttribute('href');
            if (!base) return;
            const formato = btn.getAttribute('data-export-listado');
            const params = new URLSearchParams();
            params.set('formato', formato);
            const q = searchInputEl ? searchInputEl.value.trim() : '';
            const supplier = supplierFilterEl ? supplierFilterEl.value.trim() : '';
            const date = dateFilterEl ? dateFilterEl.value : '';
            if (q) params.set('q', q);
            if (supplier) params.set('supplier', supplier);
            if (date) params.set('date', date);
            const url = base + '?' + params.toString();

            if (formato === 'pdf') {
                // PDF inline: se abre en el visor (pestaña nueva) sin generar
                // evento de descarga que IDM pueda interceptar.
                window.open(url, '_blank');
            } else {
                window.location.href = url;
            }
        });
    });
});