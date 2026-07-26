let newRowCounter = 1;
let currentCurrency = "USD";

const today = new Date();
const formattedToday = today.toISOString().split('T')[0];
const tenYearsAgo = new Date();
tenYearsAgo.setFullYear(today.getFullYear() - 10);
const formattedTenYearsAgo = tenYearsAgo.toISOString().split('T')[0];

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
                    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No hay insumos registrados en esta compra.</td></tr>`;
                    return;
                }

                const isMobile = tbody.closest('.mobile-purchase-card') !== null;

                data.details.forEach(detail => {
                    const subtotalBs = detail.quantity * detail.foreign_price * data.exchange_rate;
                    const formattedForeignPrice = detail.foreign_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    const formattedSubtotalBs = subtotalBs.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    const expDateBadge = detail.expiration_date ? `<span class="badge bg-warning text-dark border"><i class="bi bi-calendar-event me-1"></i>${detail.expiration_date.split('-').reverse().join('/')}</span>` : `<span class="text-muted small">N/A</span>`;
                    
                    let rowHtml = "";
                    if (isMobile) {
                        rowHtml = `
                            <tr>
                                <td class="p-2">
                                    <div class="d-flex justify-content-between mb-1">
                                        <span class="fw-bold text-dark small">${detail.product_sku}</span>
                                        <span class="text-secondary small fw-bold">#${detail.id}</span>
                                    </div>
                                    <div class="d-flex justify-content-between align-items-center mb-1">
                                        <span class="small text-muted">Cant: <strong class="text-primary">${detail.quantity}</strong></span>
                                        ${expDateBadge}
                                    </div>
                                    <div class="d-flex justify-content-between align-items-center mt-2 border-top pt-2">
                                        <span class="text-success small fw-semibold">${data.currency} ${formattedForeignPrice}</span>
                                        <span class="fw-bold text-dark small">Bs. ${formattedSubtotalBs}</span>
                                    </div>
                                </td>
                            </tr>
                        `;
                    } else {
                        rowHtml = `
                            <tr>
                                <td class="text-secondary fw-bold">#${detail.id}</td>
                                <td><span class="badge bg-dark text-white">${detail.product_sku}</span></td>
                                <td class="text-center fw-bold text-primary">${detail.quantity}</td>
                                <td class="text-center">${expDateBadge}</td>
                                <td class="text-end text-success fw-semibold">${data.currency} ${formattedForeignPrice}</td>
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
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-3"><i class="bi bi-exclamation-triangle-fill"></i> Error: ${error.message}</td></tr>`;
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

const modalEditElement = document.getElementById('modalEdit');
let modalEdit = null;
if (modalEditElement) {
    modalEdit = new bootstrap.Modal(modalEditElement);
}
const editPurchaseIdSpan = document.getElementById('editPurchaseId');
const editTableBody = document.getElementById('edit-table-body');
const btnSaveEdit = document.getElementById('btnSaveEdit');
const editErrorAlert = document.getElementById('editErrorAlert');
const editReasonInput = document.getElementById('editReason');
let currentEditPurchaseId = null;

const handleActionClick = function(e) {
    const triggerAnnulButton = e.target.closest('.btn-annul-trigger');
    if (triggerAnnulButton && modalAnnul) {
        const purchaseId = triggerAnnulButton.getAttribute('data-id');
        const annulUrl = triggerAnnulButton.getAttribute('data-url');
        if (annulPurchaseIdSpan) annulPurchaseIdSpan.innerText = `#${purchaseId}`;
        if (formAnnulConfirm) formAnnulConfirm.setAttribute('action', annulUrl);
        modalAnnul.show();
    }

    const triggerEditButton = e.target.closest('.btn-edit-trigger');
    if (triggerEditButton && modalEdit && editTableBody) {
        const purchaseId = triggerEditButton.getAttribute('data-id');
        currentEditPurchaseId = purchaseId;
        if (editPurchaseIdSpan) editPurchaseIdSpan.innerText = purchaseId;
        newRowCounter = 1;
        
        if (editErrorAlert) editErrorAlert.classList.add('d-none');
        if (editReasonInput) editReasonInput.value = '';
        editTableBody.innerHTML = `<tr><td colspan="4" class="text-center py-5"><div class="spinner-border text-danger" role="status"></div></td></tr>`;
        modalEdit.show();

        fetch(`/logistics/purchases/management/${purchaseId}/details`)
            .then(res => {
                if (!res.ok) throw new Error('Error en la red');
                return res.json();
            })
            .then(data => {
                editTableBody.innerHTML = '';
                currentCurrency = data.currency;
                
                if(data.details.length === 0) {
                    editTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted py-4">No hay insumos editables.</td></tr>`;
                    return;
                }
                data.details.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="ps-3 pe-3">
                            <div class="text-end text-md-start">
                                <span class="badge bg-secondary mb-1">${item.product_sku}</span><br>
                                <small class="text-muted">Registro #${item.id}</small>
                            </div>
                        </td>
                        <td class="text-center px-2">
                            <input type="number" class="form-control text-center edit-qty fw-bold text-dark border-secondary" data-id="${item.id}" value="${item.quantity}" min="0" step="0.01">
                        </td>
                        <td class="text-center px-2">
                            <input type="date" class="form-control text-center edit-exp border-secondary text-dark px-1" value="${item.expiration_date || ''}">
                        </td>
                        <td class="text-center px-2">
                            <div class="input-group">
                                <span class="input-group-text bg-light border-secondary text-muted small px-1">${data.currency}</span>
                                <input type="number" class="form-control text-end edit-price border-secondary border-start-0 ps-0 text-dark" data-id="${item.id}" value="${item.foreign_price}" min="0" step="0.01">
                            </div>
                        </td>
                    `;
                    editTableBody.appendChild(tr);
                });
            })
            .catch(err => {
                editTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger py-4"><i class="bi bi-x-circle me-1"></i> Error al cargar los datos.</td></tr>`;
            });
    }
};

const mainContainer = document.getElementById('purchases-main-container');
if (mainContainer) {
    mainContainer.addEventListener('click', handleActionClick);
}

const btnAddRowEdit = document.getElementById('btnAddRowEdit');
if (btnAddRowEdit) {
    btnAddRowEdit.addEventListener('click', function() {
        const templateEl = document.getElementById('new-product-options');
        const optionsHtml = templateEl ? templateEl.innerHTML : '<option value="" disabled selected>Seleccione...</option>';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="ps-3 pe-3">
                <div class="text-end text-md-start">
                    <select class="form-select form-select-sm edit-prod-id border-success text-dark fw-bold mb-1 w-100" data-id="new_${newRowCounter}">
                        ${optionsHtml}
                    </select>
                    <small class="text-success fw-bold"><i class="bi bi-star-fill"></i> ANEXO</small>
                </div>
            </td>
            <td class="text-center px-2">
                <input type="number" class="form-control text-center edit-qty fw-bold text-dark border-success" data-id="new_${newRowCounter}" value="1" min="0" step="0.01">
            </td>
            <td class="text-center px-2">
                <input type="date" class="form-control text-center edit-exp border-success text-dark px-1" value="">
            </td>
            <td class="text-center px-2">
                <div class="input-group">
                    <span class="input-group-text bg-success-subtle border-success text-success small px-1">${currentCurrency}</span>
                    <input type="number" class="form-control text-end edit-price border-success border-start-0 ps-0 text-dark" data-id="new_${newRowCounter}" value="0" min="0" step="0.01">
                </div>
            </td>
        `;
        if (editTableBody) editTableBody.appendChild(tr);
        newRowCounter++;
    });
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
            const prodSelect = row.querySelector('.edit-prod-id');
            
            if(qtyInput && priceInput) {
                const rowId = qtyInput.getAttribute('data-id');
                const qtyVal = parseFloat(qtyInput.value);
                const priceVal = parseFloat(priceInput.value);
                
                if (rowId.startsWith('new_')) {
                    if (!prodSelect || !prodSelect.value) {
                        formValid = false;
                        prodSelect.classList.add('is-invalid');
                    } else {
                        prodSelect.classList.remove('is-invalid');
                        items.push({
                            id: rowId,
                            product_id: parseInt(prodSelect.value),
                            quantity: qtyVal,
                            foreign_price: priceVal,
                            expiration_date: expInput ? expInput.value : ""
                        });
                    }
                } else {
                    items.push({
                        id: rowId,
                        quantity: qtyVal,
                        foreign_price: priceVal,
                        expiration_date: expInput ? expInput.value : ""
                    });
                }
            }
        });

        if (!formValid) {
            if (editErrorAlert) {
                editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>Debe seleccionar un producto para los nuevos insumos.';
                editErrorAlert.classList.remove('d-none');
            }
            return;
        }

        if (items.length === 0) return;

        btnSaveEdit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Procesando...';
        btnSaveEdit.disabled = true;

        fetch(`/logistics/purchases/management/${currentEditPurchaseId}/edit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: items, reason: reasonVal })
        })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                window.location.reload();
            } else {
                if (editErrorAlert) {
                    editErrorAlert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>' + (data.error || 'Error procesando la solicitud en el servidor.');
                    editErrorAlert.classList.remove('d-none');
                }
                btnSaveEdit.innerHTML = '<i class="bi bi-floppy me-1"></i> Guardar Cambios';
                btnSaveEdit.disabled = false;
            }
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