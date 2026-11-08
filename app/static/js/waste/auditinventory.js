document.addEventListener('DOMContentLoaded', () => {
    const filterSearch = document.getElementById('filter_search');
    const filterLocation = document.getElementById('filter_location');
    const filterSeverity = document.getElementById('filter_severity');
    const filterDate = document.getElementById('filter_date');
    const btnReset = document.getElementById('btnReset');
    const tableBody = document.querySelector('#auditTable tbody');
    const mobileContainer = document.getElementById('auditMobileContainer');
    
    const mainContainer = document.getElementById('auditMainContainer');
    const userRole = mainContainer ? mainContainer.getAttribute('data-role-id') : null;

    const actionModalElement = document.getElementById('actionAuditModal');
    let actionModal = null;
    if (actionModalElement) {
        actionModal = new bootstrap.Modal(actionModalElement);
    }
    const editQuantityContainer = document.getElementById('editQuantityContainer');
    const btnConfirmAction = document.getElementById('btnConfirmAction');
    const actionLogId = document.getElementById('actionLogId');
    const actionType = document.getElementById('actionType');
    const newQuantityInput = document.getElementById('newQuantityInput');
    const actionNotes = document.getElementById('actionNotes');

    let allLogs = [];

    const emptyStateHtml = `
        <tr>
            <td colspan="7">
                <div class="empty-state-container text-center py-4">
                    <h5 class="fw-bold text-secondary mb-1">No se encontraron resultados</h5>
                    <p class="text-muted small mb-0">Intenta ajustar los criterios de búsqueda o limpiar los filtros seleccionados.</p>
                </div>
            </td>
        </tr>
    `;

    const emptyStateMobileHtml = `
        <div class="empty-state-container text-center py-4 bg-white rounded-3 border">
            <h5 class="fw-bold text-secondary mb-1">No se encontraron resultados</h5>
            <p class="text-muted small mb-0">Intenta ajustar los criterios de búsqueda o limpiar los filtros seleccionados.</p>
        </div>
    `;

    const fetchAuditLogs = async () => {
        const locationId = filterLocation ? filterLocation.value : '';
        const severity = filterSeverity.value;

        let url = '/api/waste/audit?';
        if (locationId) url += `location_id=${locationId}&`;
        if (severity) url += `severity=${severity}`;

        try {
            const response = await fetch(url);
            const data = await response.json();

            const list = data.registros || data.logs || data.data || (Array.isArray(data) ? data : []);

            if (list && list.length > 0) {
                allLogs = list;
                renderTable(allLogs);
            } else {
                tableBody.innerHTML = emptyStateHtml;
                if (mobileContainer) mobileContainer.innerHTML = emptyStateMobileHtml;
            }
        } catch (error) {
            tableBody.innerHTML = emptyStateHtml;
            if (mobileContainer) mobileContainer.innerHTML = emptyStateMobileHtml;
        }
    };

    const renderTable = (logs) => {
        const searchText = filterSearch.value.toLowerCase().trim();
        const selectedDate = filterDate.value;

        const filtered = logs.filter(log => {
            let details = {};
            if (typeof log.changed_data === 'string') {
                try { details = JSON.parse(log.changed_data); } catch(e) { details = {}; }
            } else {
                details = log.changed_data || {};
            }

            const userName = log.user_name || log.usuario || log.user || 'Sistema';
            const productName = log.product_name || details.product_name || log.producto || '';
            const actionName = log.action || log.accion || log.acción || '';
            const locationName = log.location_name || log.sede || log.location || 'Almacén Principal';

            const matchSearch = 
                userName.toLowerCase().includes(searchText) ||
                productName.toLowerCase().includes(searchText) ||
                actionName.toLowerCase().includes(searchText) ||
                locationName.toLowerCase().includes(searchText);

            let matchDate = true;
            if (selectedDate && log.timestamp) {
                matchDate = log.timestamp.startsWith(selectedDate);
            }

            return matchSearch && matchDate;
        });

        if (filtered.length === 0) {
            tableBody.innerHTML = emptyStateHtml;
            if (mobileContainer) mobileContainer.innerHTML = emptyStateMobileHtml;
            return;
        }

        tableBody.innerHTML = '';
        if (mobileContainer) mobileContainer.innerHTML = '';

        const now = new Date(); 

        filtered.forEach((log, index) => {
            let details = {};
            if (typeof log.changed_data === 'string') {
                try { details = JSON.parse(log.changed_data); } catch(e) { details = {}; }
            } else {
                details = log.changed_data || {};
            }

            const userName = log.user_name || log.usuario || log.user || 'Sistema';
            const initial = userName.charAt(0).toUpperCase();
            const productName = log.product_name || details.product_name || log.producto || 'Insumo';
            const locationName = log.location_name || log.sede || log.location || 'Almacén Principal';
            const qty = parseFloat(log.quantity_changed !== undefined ? log.quantity_changed : (details.quantity_changed || 0));
            
            let prevQty = parseFloat(log.previous_quantity !== undefined ? log.previous_quantity : (details.previous_quantity || 0));
            let newQty = parseFloat(log.new_quantity !== undefined ? log.new_quantity : (details.new_quantity || 0));

            if (prevQty === 0 && newQty === 0 && qty !== 0) {
                if (qty < 0) {
                    prevQty = Math.abs(qty);
                    newQty = 0;
                } else {
                    prevQty = 0;
                    newQty = qty;
                }
            }

            const notes = log.notes || details.notes || 'Registro de movimiento de inventario';
            const logId = log.id || (index + 1);

            let variationClass = 'text-danger fw-bold';
            let variationPrefix = '';

            if (qty > 0) {
                variationClass = 'text-success fw-bold';
                variationPrefix = '+';
            } else if (qty === 0 && newQty > prevQty) {
                variationClass = 'text-success fw-bold';
                variationPrefix = '+';
            }

            let severityHtml = '';
            const sev = (log.severity || log.severidad || 'NORMAL').toUpperCase();
            if (sev === 'ALERTA') {
                severityHtml = `<span class="badge bg-warning text-dark"><i class="bi bi-triangle-fill me-1"></i>ALERTA (BAJO)</span>`;
            } else if (sev === 'CRITICO' || sev === 'CRÍTICO') {
                severityHtml = `<span class="badge bg-danger"><i class="bi bi-exclamation-circle-fill me-1"></i>CRÍTICO</span>`;
            } else if (sev === 'REABASTECIDO' || sev === 'REABASTECIMIENTO') {
                severityHtml = `<span class="badge bg-info text-white"><i class="bi bi-arrow-up-circle-fill me-1"></i>REABASTECIDO</span>`;
            } else if (sev === 'EDITADO') {
                severityHtml = `<span class="badge bg-warning text-dark"><i class="bi bi-pencil-fill me-1"></i>EDITADO</span>`;
            } else if (sev === 'ANULADO') {
                severityHtml = `<span class="badge bg-danger"><i class="bi bi-x-circle-fill me-1"></i>ANULADO</span>`;
            } else {
                severityHtml = `<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>NORMAL</span>`;
            }

            const actionText = (log.action || log.accion || log.acción || 'MOVIMIENTO').replace(/_/g, ' ');
            const isRest = actionText.toLowerCase().includes('gasto') || actionText.toLowerCase().includes('merma') || actionText.toLowerCase().includes('salida') || actionText.toLowerCase().includes('anular');
            const isAdd = actionText.toLowerCase().includes('ingreso') || actionText.toLowerCase().includes('compra') || actionText.toLowerCase().includes('reabastecimiento') || actionText.toLowerCase().includes('ajuste') || actionText.toLowerCase().includes('activacion');

            let actionBadgeStyle = 'background-color: #e3f2fd; color: #1565c0; border: 1px solid #bbdefb;';
            if (isRest) {
                actionBadgeStyle = 'background-color: #ffebee; color: #c62828; border: 1px solid #ffcdd2;';
            } else if (isAdd) {
                actionBadgeStyle = 'background-color: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9;';
            }

            let dateStr = log.timestamp || '';
            let timeStr = '';
            
            let logDateObj = null;
            if (dateStr) {
                const isoFormat = dateStr.replace(' ', 'T') + 'Z'; 
                logDateObj = new Date(isoFormat);
            }

            if (dateStr.includes('T')) {
                const parts = dateStr.split('T');
                dateStr = parts[0];
                timeStr = parts[1].substring(0, 5);
            } else if (dateStr.includes(' ')) {
                const parts = dateStr.split(' ');
                dateStr = parts[0];
                timeStr = parts[1].substring(0, 5);
            }

            let diffHours = 0;
            if (logDateObj) {
                diffHours = Math.abs(now - logDateObj) / 36e5;
            }

            let actionButtonsHtml = '';
            const actionIsReversionOrAdjust = actionText.includes('AJUSTE') || actionText.includes('REVERSION') || actionText.includes('ACTIVACION');
            const actionIsPurchase = actionText.includes('COMPRA') || actionText.includes('INGRESO');
            
            if (userRole !== '6' && !actionIsReversionOrAdjust && !actionIsPurchase) {
                if (userRole !== '1' && diffHours > 24) {
                    actionButtonsHtml = `<div class="badge bg-secondary p-2 mt-2"><i class="bi bi-clock-history me-1"></i>Tiempo expirado (24h). Solicite corrección al Administrador.</div>`;
                } else if (userRole === '1' && diffHours > 720) {
                    actionButtonsHtml = `<div class="badge bg-danger p-2 mt-2"><i class="bi bi-clock-history me-1"></i>Plazo máximo administrativo expirado (30 días).</div>`;
                } else {
                    if (sev === 'ANULADO') {
                        actionButtonsHtml = `
                            <div class="mt-3 border-top pt-2">
                                <button class="btn btn-sm btn-outline-success me-2 btn-action-log" data-action="ACTIVAR" data-id="${logId}">
                                    <i class="bi bi-check-circle me-1"></i>Activar
                                </button>
                            </div>
                        `;
                    } else if (sev !== 'EDITADO') {
                        actionButtonsHtml = `
                            <div class="mt-3 border-top pt-2">
                                <button class="btn btn-sm btn-outline-primary me-2 btn-action-log" data-action="EDITAR" data-id="${logId}">
                                    <i class="bi bi-pencil-square me-1"></i>Editar
                                </button>
                                <button class="btn btn-sm btn-outline-danger btn-action-log" data-action="ANULAR" data-id="${logId}">
                                    <i class="bi bi-x-circle me-1"></i>Anular
                                </button>
                            </div>
                        `;
                    }
                }
            }

            if (dateStr.includes('-')) {
                const dParts = dateStr.split('-');
                if (dParts.length === 3) {
                    dateStr = `${dParts[2]}/${dParts[1]}/${dParts[0]}`;
                }
            }

            const detailRowId = `detail_row_${logId}_${index}`;
            const mobileDetailId = `mobile_detail_${logId}_${index}`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="ps-3">
                    <div class="d-flex align-items-center">
                        <div class="rounded-circle bg-secondary text-white d-flex align-items-center justify-content-center me-2 fw-bold" style="width: 32px; height: 32px; font-size: 0.85rem;">
                            ${initial}
                        </div>
                        <div>
                            <div class="fw-bold text-dark small mb-0">${userName}</div>
                        </div>
                    </div>
                </td>
                <td><span class="badge rounded-pill px-3 py-2 text-uppercase" style="${actionBadgeStyle} font-size: 0.725rem;">${actionText}</span></td>
                <td>
                    <div class="fw-bold text-dark small mb-0">${productName}</div>
                    <small class="text-muted" style="font-size: 0.725rem;"><i class="bi bi-geo-alt"></i> ${locationName}</small>
                </td>
                <td class="text-center"><span class="${variationClass}">${variationPrefix}${qty.toFixed(1)}</span></td>
                <td>${severityHtml}</td>
                <td>
                    <div class="fw-bold text-dark small mb-0">${dateStr}</div>
                    <small class="text-muted" style="font-size: 0.7rem;">${timeStr}</small>
                </td>
                <td class="text-end pe-3">
                    <button class="btn btn-outline-secondary btn-sm toggle-detail-btn" data-target="${detailRowId}">
                        <i class="bi bi-chevron-down me-1 icon-chevron"></i>Detalle
                    </button>
                </td>
            `;

            const trDetail = document.createElement('tr');
            trDetail.id = detailRowId;
            trDetail.classList.add('d-none');
            trDetail.innerHTML = `
                <td colspan="7" class="p-0 border-0">
                    <div class="p-3 bg-light border-start border-3 border-secondary my-2 mx-3 rounded-2 shadow-sm">
                        <div class="row text-uppercase text-muted fw-bold mb-1" style="font-size: 0.7rem;">
                            <div class="col-md-3">Stock Anterior</div>
                            <div class="col-md-3">Nuevo Stock</div>
                            <div class="col-md-3">Variación Stock</div>
                            <div class="col-md-3">ID Log</div>
                        </div>
                        <div class="row fw-bold text-dark mb-3" style="font-size: 0.9rem;">
                            <div class="col-md-3">${prevQty.toFixed(1)}</div>
                            <div class="col-md-3">${newQty.toFixed(1)}</div>
                            <div class="col-md-3 ${variationClass}">${variationPrefix}${qty.toFixed(1)}</div>
                            <div class="col-md-3 text-muted">#${logId}</div>
                        </div>
                        <div class="pt-2 border-top">
                            <div class="text-uppercase text-muted fw-bold mb-1" style="font-size: 0.7rem;">
                                <i class="bi bi-chat-left-text me-1"></i>Observaciones / Motivo
                            </div>
                            <div class="text-secondary small mb-0">${notes}</div>
                            ${actionButtonsHtml}
                        </div>
                    </div>
                </td>
            `;

            tableBody.appendChild(tr);
            tableBody.appendChild(trDetail);

            if (mobileContainer) {
                const card = document.createElement('div');
                card.className = 'mobile-audit-card';
                card.innerHTML = `
                    <div class="card-header-mobile">
                        <div class="user-info">
                            <div class="user-avatar">${initial}</div>
                            <div><div class="fw-bold text-dark small">${userName}</div></div>
                        </div>
                        <div class="text-end">
                            <div class="fw-semibold text-dark" style="font-size: 0.75rem;">${dateStr}</div>
                            <div class="text-muted" style="font-size: 0.7rem;">${timeStr}</div>
                        </div>
                    </div>
                    <div class="row g-2 my-1">
                        <div class="col-8">
                            <div class="mobile-label">Insumo / Sede</div>
                            <div class="mobile-value fw-bold text-dark">${productName}</div>
                            <div class="text-muted small" style="font-size: 0.75rem;"><i class="bi bi-geo-alt"></i> ${locationName}</div>
                        </div>
                        <div class="col-4 text-end">
                            <div class="mobile-label">Variación</div>
                            <div class="mobile-value fs-6 ${variationClass}">${variationPrefix}${qty.toFixed(1)}</div>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center mt-3 pt-2 border-top">
                        <div class="d-flex align-items-center gap-1 flex-wrap">
                            <span class="badge rounded-pill px-2 py-1 text-uppercase" style="${actionBadgeStyle} font-size: 0.65rem;">${actionText}</span>
                            ${severityHtml}
                        </div>
                        <button class="btn btn-outline-secondary btn-sm toggle-mobile-detail-btn" data-target="${mobileDetailId}">
                            <i class="bi bi-chevron-down me-1 icon-chevron"></i>Detalle
                        </button>
                    </div>
                    <div id="${mobileDetailId}" class="d-none mt-3 pt-2 border-top bg-light p-2 rounded">
                        <div class="row text-center g-2 mb-2">
                            <div class="col-4">
                                <div class="mobile-label">Anterior</div>
                                <div class="fw-bold small text-dark">${prevQty.toFixed(1)}</div>
                            </div>
                            <div class="col-4">
                                <div class="mobile-label">Nuevo</div>
                                <div class="fw-bold small text-dark">${newQty.toFixed(1)}</div>
                            </div>
                            <div class="col-4">
                                <div class="mobile-label">ID Log</div>
                                <div class="fw-bold small text-muted">#${logId}</div>
                            </div>
                        </div>
                        <div class="pt-2 border-top">
                            <div class="mobile-label"><i class="bi bi-chat-left-text me-1"></i>Observaciones</div>
                            <div class="text-secondary small">${notes}</div>
                            ${actionButtonsHtml}
                        </div>
                    </div>
                `;
                mobileContainer.appendChild(card);
            }
        });

        document.querySelectorAll('.toggle-detail-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const detailRow = document.getElementById(targetId);
                const chevron = btn.querySelector('.icon-chevron');
                if (detailRow) {
                    if (detailRow.classList.contains('d-none')) {
                        detailRow.classList.remove('d-none');
                        chevron.classList.replace('bi-chevron-down', 'bi-chevron-up');
                    } else {
                        detailRow.classList.add('d-none');
                        chevron.classList.replace('bi-chevron-up', 'bi-chevron-down');
                    }
                }
            });
        });

        document.querySelectorAll('.toggle-mobile-detail-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const detailBox = document.getElementById(targetId);
                const chevron = btn.querySelector('.icon-chevron');
                if (detailBox) {
                    if (detailBox.classList.contains('d-none')) {
                        detailBox.classList.remove('d-none');
                        chevron.classList.replace('bi-chevron-down', 'bi-chevron-up');
                    } else {
                        detailBox.classList.add('d-none');
                        chevron.classList.replace('bi-chevron-up', 'bi-chevron-down');
                    }
                }
            });
        });

        document.querySelectorAll('.btn-action-log').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const lId = btn.getAttribute('data-id');
                const type = btn.getAttribute('data-action');
                
                actionLogId.value = lId;
                actionType.value = type;
                actionNotes.value = '';
                newQuantityInput.value = '';

                document.getElementById('actionAuditModalLabel').innerText = `Confirmar Acción: ${type}`;
                
                if (type === 'EDITAR') {
                    editQuantityContainer.style.display = 'block';
                } else {
                    editQuantityContainer.style.display = 'none';
                }

                if (actionModal) actionModal.show();
            });
        });
    };

    if (btnConfirmAction) {
        btnConfirmAction.addEventListener('click', async () => {
            const lId = actionLogId.value;
            const type = actionType.value;
            const notes = actionNotes.value.trim();
            const newQty = newQuantityInput.value;

            if (!notes) {
                alert('Debe justificar obligatoriamente el motivo de la acción.');
                return;
            }

            if (type === 'EDITAR' && newQty === '') {
                alert('Debe ingresar la nueva variación para editar el registro.');
                return;
            }

            btnConfirmAction.disabled = true;
            btnConfirmAction.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Procesando...';

            try {
                const response = await fetch('/api/waste/audit/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        log_id: lId,
                        action_type: type,
                        notes: notes,
                        new_quantity: newQty ? parseFloat(newQty) : null
                    })
                });

                const result = await response.json();

                if (result.success) {
                    if (actionModal) actionModal.hide();
                    fetchAuditLogs(); 
                } else {
                    alert('Error: ' + result.message);
                }
            } catch (error) {
                alert('Error en la comunicación con el servidor.');
            } finally {
                btnConfirmAction.disabled = false;
                btnConfirmAction.innerText = 'Procesar Acción';
            }
        });
    }

    if (filterLocation) filterLocation.addEventListener('change', fetchAuditLogs);
    filterSeverity.addEventListener('change', fetchAuditLogs);
    filterSearch.addEventListener('input', () => renderTable(allLogs));
    filterDate.addEventListener('change', () => renderTable(allLogs));

    btnReset.addEventListener('click', () => {
        filterSearch.value = '';
        filterSeverity.value = '';
        filterDate.value = '';
        if (filterLocation && !filterLocation.disabled) filterLocation.value = '';
        fetchAuditLogs();
    });

    fetchAuditLogs();
});