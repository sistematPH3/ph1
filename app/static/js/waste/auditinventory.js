document.addEventListener('DOMContentLoaded', () => {
    const filterSearch = document.getElementById('filter_search');
    const filterLocation = document.getElementById('filter_location');
    const filterSeverity = document.getElementById('filter_severity');
    const filterDate = document.getElementById('filter_date');
    const btnReset = document.getElementById('btnReset');
    const tableBody = document.querySelector('#auditTable tbody');
    const mobileContainer = document.getElementById('auditMobileContainer'); // Nuevo contenedor móvil

    let allLogs = [];

    // Mensaje para estado vacío (Escritorio)
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

    // Mensaje para estado vacío (Móvil)
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
            console.error("Error al obtener auditoría:", error);
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

            // Variación del movimiento
            const qty = parseFloat(log.quantity_changed !== undefined ? log.quantity_changed : (details.quantity_changed || 0));

            // Lectura directa y calculada
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

            // Severidad
            let severityHtml = '';
            const sev = (log.severity || log.severidad || 'NORMAL').toUpperCase();
            if (sev === 'ALERTA') {
                severityHtml = `<span class="badge bg-warning text-dark"><i class="bi bi-triangle-fill me-1"></i>ALERTA (BAJO)</span>`;
            } else if (sev === 'CRITICO' || sev === 'CRÍTICO') {
                severityHtml = `<span class="badge bg-danger"><i class="bi bi-exclamation-circle-fill me-1"></i>CRÍTICO</span>`;
            } else if (sev === 'REABASTECIDO' || sev === 'REABASTECIMIENTO') {
                severityHtml = `<span class="badge bg-info text-white"><i class="bi bi-arrow-up-circle-fill me-1"></i>REABASTECIDO</span>`;
            } else {
                severityHtml = `<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>NORMAL</span>`;
            }

            // Acción
            const actionText = (log.action || log.accion || log.acción || 'MOVIMIENTO').replace(/_/g, ' ');
            
            const isRest = actionText.toLowerCase().includes('gasto') || actionText.toLowerCase().includes('merma') || actionText.toLowerCase().includes('salida');
            const isAdd = actionText.toLowerCase().includes('ingreso') || actionText.toLowerCase().includes('compra') || actionText.toLowerCase().includes('reabastecimiento');

            let actionBadgeStyle = 'background-color: #e3f2fd; color: #1565c0; border: 1px solid #bbdefb;';
            if (isRest) {
                actionBadgeStyle = 'background-color: #ffebee; color: #c62828; border: 1px solid #ffcdd2;';
            } else if (isAdd) {
                actionBadgeStyle = 'background-color: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9;';
            }

            // Formato de Fecha / Hora
            let dateStr = log.timestamp || '';
            let timeStr = '';
            if (dateStr.includes('T')) {
                const parts = dateStr.split('T');
                dateStr = parts[0];
                timeStr = parts[1].substring(0, 5);
            } else if (dateStr.includes(' ')) {
                const parts = dateStr.split(' ');
                dateStr = parts[0];
                timeStr = parts[1].substring(0, 5);
            }

            if (dateStr.includes('-')) {
                const dParts = dateStr.split('-');
                if (dParts.length === 3) {
                    dateStr = `${dParts[2]}/${dParts[1]}/${dParts[0]}`;
                }
            }

            const detailRowId = `detail_row_${logId}_${index}`;
            const mobileDetailId = `mobile_detail_${logId}_${index}`;

            // ==========================================
            // 1. RENDERIZADO ESCRITORIO (TABLA)
            // ==========================================
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
                <td>
                    <span class="badge rounded-pill px-3 py-2 text-uppercase" style="${actionBadgeStyle} font-size: 0.725rem;">${actionText}</span>
                </td>
                <td>
                    <div class="fw-bold text-dark small mb-0">${productName}</div>
                    <small class="text-muted" style="font-size: 0.725rem;"><i class="bi bi-geo-alt"></i> ${locationName}</small>
                </td>
                <td class="text-center">
                    <span class="${variationClass}">${variationPrefix}${qty.toFixed(1)}</span>
                </td>
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
                        <div class="row text-uppercase text-muted fw-bold mb-1" style="font-size: 0.7rem; letter-spacing: 0.5px;">
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
                            <div class="text-uppercase text-muted fw-bold mb-1" style="font-size: 0.7rem; letter-spacing: 0.5px;">
                                <i class="bi bi-chat-left-text me-1"></i>Observaciones / Motivo
                            </div>
                            <div class="text-secondary small mb-0">${notes}</div>
                        </div>
                    </div>
                </td>
            `;

            tableBody.appendChild(tr);
            tableBody.appendChild(trDetail);

            // ==========================================
            // 2. RENDERIZADO MÓVIL (TARJETAS)
            // ==========================================
            if (mobileContainer) {
                const card = document.createElement('div');
                card.className = 'mobile-audit-card';
                card.innerHTML = `
                    <div class="card-header-mobile">
                        <div class="user-info">
                            <div class="user-avatar">${initial}</div>
                            <div>
                                <div class="fw-bold text-dark small">${userName}</div>
                            </div>
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

                    <!-- Detalle Desplegable Móvil -->
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
                        </div>
                    </div>
                `;
                mobileContainer.appendChild(card);
            }
        });

        // Listeners para desplegar detalle en Escritorio
        document.querySelectorAll('.toggle-detail-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const detailRow = document.getElementById(targetId);
                const chevron = btn.querySelector('.icon-chevron');

                if (detailRow) {
                    const isHidden = detailRow.classList.contains('d-none');
                    if (isHidden) {
                        detailRow.classList.remove('d-none');
                        chevron.classList.replace('bi-chevron-down', 'bi-chevron-up');
                    } else {
                        detailRow.classList.add('d-none');
                        chevron.classList.replace('bi-chevron-up', 'bi-chevron-down');
                    }
                }
            });
        });

        // Listeners para desplegar detalle en Móvil
        document.querySelectorAll('.toggle-mobile-detail-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const detailBox = document.getElementById(targetId);
                const chevron = btn.querySelector('.icon-chevron');

                if (detailBox) {
                    const isHidden = detailBox.classList.contains('d-none');
                    if (isHidden) {
                        detailBox.classList.remove('d-none');
                        chevron.classList.replace('bi-chevron-down', 'bi-chevron-up');
                    } else {
                        detailBox.classList.add('d-none');
                        chevron.classList.replace('bi-chevron-up', 'bi-chevron-down');
                    }
                }
            });
        });
    };

    // Listeners de los filtros
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