document.addEventListener('DOMContentLoaded', function () {

    // Elementos y estado global
    const isAdmin = window.WASTE_IS_ADMIN === true;
    const tableBody = document.getElementById('approvalTableBody');
    const searchInput = document.getElementById('searchApprovalInput');
    const pendingBadge = document.getElementById('pendingCountBadge');
    const alertsBox = document.getElementById('approvalAlerts');

    // Modal de detalle / decisión (un solo modal reutilizado)
    const approvalModalEl = document.getElementById('approvalModal');
    const approvalModal = bootstrap.Modal.getOrCreateInstance(approvalModalEl);
    const modalBody = document.getElementById('approvalModalBody');
    const modalFooter = document.getElementById('approvalModalFooter');
    const decisionButtons = document.getElementById('decisionButtons');
    const rejectReasonWrap = document.getElementById('rejectReasonWrap');
    const rejectReason = document.getElementById('rejectReason');
    const rejectReasonError = document.getElementById('rejectReasonError');
    const btnRejectModal = document.getElementById('btnRejectModal');
    const btnConfirmApprove = document.getElementById('btnConfirmApprove');
    const btnConfirmReject = document.getElementById('btnConfirmReject');

    // Vista de confirmación (dentro del mismo modal)
    const confirmDecisionBody = document.getElementById('confirmDecisionBody');
    const confirmButtons = document.getElementById('confirmButtons');
    const btnConfirmCancel = document.getElementById('btnConfirmCancel');
    const btnConfirmDecisionOk = document.getElementById('btnConfirmDecisionOk');

    let wastesList = [];
    let currentWaste = null;
    let pendingDecision = null;

    // Limpiar el modo de confirmación cuando se cierra el modal (X / Cerrar / clic fuera)
    approvalModalEl.addEventListener('hidden.bs.modal', function () {
        approvalModalEl.classList.remove('confirm-mode');
        document.body.classList.remove('ph-confirm-blur');
    });

    function showAlert(message, isError) {
        const cls = isError ? 'alert-danger' : 'alert-success';
        const icon = isError ? 'bi-exclamation-triangle' : 'bi-check-circle';
        if (!alertsBox) return;
        alertsBox.innerHTML = '';
        const div = document.createElement('div');
        div.className = 'alert ' + cls + ' alert-dismissible fade show';
        div.setAttribute('role', 'alert');
        div.innerHTML = '<i class="bi ' + icon + ' me-1"></i> ' + message +
            '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';
        alertsBox.appendChild(div);
        setTimeout(function () { alertsBox.innerHTML = ''; }, 6000);
    }

    function esc(str) {
        const div = document.createElement('div');
        div.textContent = (str == null) ? '' : String(str);
        return div.innerHTML;
    }

    function formatFecha(value) {
        if (!value) return '—';
        let d;
        if (value instanceof Date) {
            d = value;
        } else {
            const num = new Date(value).getTime();
            if (isNaN(num)) return value;
            d = new Date(num);
        }
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yyyy = d.getFullYear();
        const hh = String(d.getHours()).padStart(2, '0');
        const min = String(d.getMinutes()).padStart(2, '0');
        return dd + '/' + mm + '/' + yyyy + ' ' + hh + ':' + min;
    }

    function badgeTipo(requiresApproval) {
        if (requiresApproval) {
            return '<span class="badge bg-warning text-dark border"><i class="bi bi-exclamation-triangle me-1"></i>Aprobación requerida</span>';
        }
        return '<span class="badge bg-secondary text-white"><i class="bi bi-dash-circle me-1"></i>Automática</span>';
    }

    var NOVEDAD_MAP = {
        cantidad: ['Cantidad', 'nov-qty', 'bi-box-seam'],
        tipo: ['Tipo sensible', 'nov-type', 'bi-exclamation-triangle'],
        tiempo: ['Tiempo', 'nov-time', 'bi-clock-history'],
        info: ['Revisión', 'nov-info', 'bi-question-circle']
    };

    function chipsNovedad(n) {
        if (!n || !n.motivos) return '';
        return n.motivos.map(function (m) {
            var def = NOVEDAD_MAP[m] || NOVEDAD_MAP.info;
            return '<span class="nov-badge ' + def[1] + '"><i class="bi ' + def[2] + '"></i>' + def[0] + '</span>';
        }).join(' ');
    }

    function bloqueNovedad(n) {
        if (!n) return '';
        var razones = (n.razones || []).map(function (r) {
            return '<li>' + esc(r) + '</li>';
        }).join('');
        var tiempoHtml = '';
        if (n.por_tiempo) {
            var esp = (n.esperado == null) ? '—' : (+n.esperado).toFixed(2);
            var umb = (n.umbral == null) ? '—' : (+n.umbral).toFixed(2);
            tiempoHtml =
                '<div class="row small g-2 mt-2 border-top pt-2 text-center">' +
                    '<div class="col-4"><span class="text-muted d-block">Esperado</span><div class="fw-bold">' + esp + '</div></div>' +
                    '<div class="col-4"><span class="text-muted d-block">Umbral</span><div class="fw-bold">' + umb + '</div></div>' +
                    '<div class="col-4"><span class="text-muted d-block">Registrado</span><div class="fw-bold">' + n.registrado + '</div></div>' +
                '</div>';
        }
        return '<div class="mb-3 rounded p-3" style="background:#f8f9fa;border:1px solid #eee;">' +
            '<div class="small fw-semibold text-uppercase text-muted mb-2"><i class="bi bi-exclamation-octagon me-1"></i>Motivo de la novedad</div>' +
            '<div class="mb-2">' + chipsNovedad(n) + '</div>' +
            (razones ? '<ul class="small mb-0">' + razones + '</ul>' : '') +
            tiempoHtml +
            '</div>';
    }

    function renderCount(count) {
        if (pendingBadge) {
            pendingBadge.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Pendientes: ' + count;
        }
    }

    function applySearchFilter() {
        if (!tableBody) return;
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        tableBody.querySelectorAll('tr').forEach(function (row) {
            if (row.id && row.id.indexOf('emptylist') !== -1) return;
            row.style.display = row.textContent.toLowerCase().includes(query) ? '' : 'none';
        });
    }

    function renderTable(rows) {
        if (!tableBody) return;
        if (!rows || rows.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-5">' +
                '<i class="bi bi-check2-all fs-1 d-block mb-2"></i>No hay mermas pendientes de aprobación.</td></tr>';
            renderCount(0);
            return;
        }

        let html = '';
        rows.forEach(function (w) {
            const motivo = (w.notes && String(w.notes).trim()) ? String(w.notes) : '';
            html += '<tr>' +
                '<td class="fw-bold"><div class="d-flex align-items-center">' +
                '<div class="rounded-circle bg-danger text-white d-flex align-items-center justify-content-center me-3 shadow-sm" style="width:40px;height:40px;font-weight:bold;">' + w.id + '</div>' +
                '<div><span class="text-dark d-block fw-bold">' + esc(w.type_name) + '</span>' + badgeTipo(w.type_requires_approval) + '</div>' +
                '</div></td>' +
                '<td data-label="Sede"><span class="ph-badge-location">' + esc(w.location_name) + '</span></td>' +
                '<td data-label="Cantidad" class="fw-bold" style="color:#af1515;font-size:1.1rem;">' + w.total_quantity +
                '<span class="text-muted fw-normal" style="font-size:0.8rem;"> uds.</span></td>' +
                '<td data-label="Autor">' + esc(w.author_name) + '</td>' +
                '<td data-label="Fecha" class="text-muted small">' + formatFecha(w.date) + '</td>' +
                '<td data-label="Motivo" class="text-muted small text-truncate" style="max-width:180px;">' +
                (motivo ? esc(motivo) : '<span class="text-secondary fst-italic">Sin motivo</span>') + '</td>' +
                '<td data-label="Novedad"><div class="nov-wrap">' + chipsNovedad(w.novelty) + '</div></td>' +
                '<td class="text-end"><button type="button" class="btn btn-sm btn-outline-danger rounded-pill px-3 btn-ver-merma" ' +
                'data-id="' + w.id + '" title="Ver detalle y aprobar/rechazar"><i class="bi bi-eye me-1"></i>Ver y resolver</button></td>' +
                '</tr>';
        });
        tableBody.innerHTML = html;

        tableBody.querySelectorAll('.btn-ver-merma').forEach(function (btn) {
            btn.addEventListener('click', function () {
                openDetail(Number(this.dataset.id));
            });
        });

        renderCount(rows.length);
        applySearchFilter();
    }

    async function loadPending() {
        try {
            const res = await fetch('/api/waste/merma/approvals', {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!res.ok) throw new Error('No se pudo cargar la bandeja.');
            const data = await res.json();
            if (!data.success) throw new Error(data.message || 'Error al cargar.');
            wastesList = data.wastes || [];
            renderTable(wastesList);
        } catch (err) {
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-5"><i class="bi bi-exclamation-triangle fs-1 d-block mb-2"></i>' + esc(err.message) + '</td></tr>';
            }
        }
    }

    function mostrarVistaDetalle() {
        confirmDecisionBody.style.display = 'none';
        modalBody.style.display = '';
        decisionButtons.style.display = isAdmin && currentWaste && currentWaste.status === 'PENDIENTE' && currentWaste.puede_resolver ? 'flex' : 'none';
        confirmButtons.style.display = 'none';
        rejectReasonWrap.style.display = 'none';
        btnConfirmApprove.style.display = 'inline-block';
        btnConfirmReject.style.display = 'none';
        modalFooter.style.display = 'flex';
    }

    async function openDetail(id) {
        currentWaste = null;
        approvalModalEl.classList.remove('confirm-mode');
        document.body.classList.remove('ph-confirm-blur');
        modalBody.style.display = '';
        confirmDecisionBody.style.display = 'none';
        modalBody.innerHTML = '<div class="text-center text-muted py-5">Cargando detalle...</div>';
        modalFooter.style.display = 'none';
        decisionButtons.style.display = 'none';
        confirmButtons.style.display = 'none';
        rejectReasonWrap.style.display = 'none';
        rejectReasonError.style.display = 'none';
        approvalModal.show();

        try {
            const res = await fetch('/api/waste/merma/' + id, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!res.ok) {
                const e = await res.json().catch(function () { return {}; });
                throw new Error(e.message || 'No se pudo cargar el detalle.');
            }
            const data = await res.json();
            if (!data.success) throw new Error(data.message || 'Error al cargar el detalle.');
            currentWaste = data.waste;
            fillDetail(currentWaste);
        } catch (err) {
            modalBody.innerHTML = '<div class="alert alert-danger">' + esc(err.message) + '</div>';
            modalFooter.style.display = 'none';
        }
    }

    function fillDetail(w) {
        approvalModalEl.classList.remove('confirm-mode');
        document.body.classList.remove('ph-confirm-blur');
        modalBody.style.display = '';
        confirmDecisionBody.style.display = 'none';
        let fotoHtml = '';
        if (w.evidence_url) {
            fotoHtml = '<div class="mb-3"><div class="small text-muted fw-semibold mb-1"><i class="bi bi-image me-1"></i>Evidencia fotográfica</div>' +
                '<img src="' + esc(w.evidence_url) + '" class="img-fluid rounded border" style="max-height:180px;" alt="Evidencia"></div>';
        } else {
            fotoHtml = '<div class="mb-3 border rounded p-3 text-center bg-light"><div class="small text-muted fw-semibold mb-1"><i class="bi bi-image me-1"></i>Evidencia fotográfica</div>' +
                '<span class="text-muted fst-italic small"><i class="bi bi-camera-off me-1"></i>No se adjuntó foto</span></div>';
        }

        let rowsHtml = '';
        if (w.lines && w.lines.length > 0) {
            w.lines.forEach(function (l) {
                const limite = (l.waste_limit != null) ? l.waste_limit : null;
                let limiteHtml;
                if (limite != null) {
                    let estado = l.excede_limite
                        ? '<div class="small text-danger fw-semibold"><i class="bi bi-exclamation-triangle me-1"></i>Excede el límite</div>'
                        : '<div class="small text-muted fst-italic">Dentro del límite</div>';
                    limiteHtml = '<span class="fw-bold ' + (l.excede_limite ? 'text-danger' : 'text-success') + '">' +
                        limite + '<span class="text-muted fw-normal small"> ' + esc(l.unit || '') + '</span></span>' + estado;
                } else {
                    limiteHtml = '<span class="text-muted fst-italic small">Sin configurar</span>';
                }
                const stockOk = parseFloat(l.stock_en_lote) >= parseFloat(l.quantity);
                rowsHtml += '<tr>' +
                    '<td>' + esc(l.product_name) + '</td>' +
                    '<td><span class="badge bg-light text-dark border font-monospace">' + esc(l.lot_number || 'N/A') + '</span></td>' +
                    '<td class="text-muted small">' + esc(l.expiration_date) + '</td>' +
                    '<td class="fw-bold text-dark">' + l.quantity + ' <span class="text-muted small fw-normal">' + esc(l.unit || '') + '</span></td>' +
                    '<td>' + limiteHtml + '</td>' +
                    '<td><span class="badge ' + (stockOk ? 'bg-success' : 'bg-danger') + '">' +
                    Number(l.stock_en_lote).toLocaleString('en-US', { minimumFractionDigits: 2 }) +
                    '</span> <span class="text-muted small">en sede</span></td></tr>';
            });
        } else {
            rowsHtml = '<tr><td colspan="6" class="text-center text-muted py-3">Sin líneas de detalle.</td></tr>';
        }

        modalBody.innerHTML =
            fotoHtml +
            '<div class="row g-3 mb-3">' +
            '<div class="col-md-6"><div class="border rounded p-2"><span class="text-muted small">Sede</span><div class="fw-bold">' + esc(w.location_name) + '</div></div></div>' +
            '<div class="col-md-6"><div class="border rounded p-2"><span class="text-muted small">Tipo de merma</span><div class="fw-bold">' + esc(w.type_name) + '</div></div></div>' +
            '<div class="col-md-4"><div class="border rounded p-2"><span class="text-muted small">Registrado por</span><div class="fw-bold">' + esc(w.author_name) + '</div></div></div>' +
            '<div class="col-md-4"><div class="border rounded p-2"><span class="text-muted small">Fecha</span><div class="fw-bold">' + formatFecha(w.date) + '</div></div></div>' +
            '<div class="col-md-4"><div class="border rounded p-2"><span class="text-muted small">Cantidad total</span><div class="fw-bold text-danger">' + w.total_quantity + ' uds.</div></div></div>' +
            '</div>' +
            '<div class="mb-2 small text-muted fw-semibold">Motivo / Observaciones</div>' +
            '<div class="alert alert-light border text-dark">' + esc(w.notes || '—') + '</div>' +
            (w.es_autor
                ? '<div class="alert alert-warning border-0 py-2 small"><i class="bi bi-shield-lock me-2"></i>Usted registró esta merma. La decisión (aprobar/rechazar) debe tomarla <b>otro administrador</b>.</div>'
                : '') +
            bloqueNovedad(w.novelty) +
            '<div class="mb-2 small text-muted fw-semibold">Detalle de líneas</div>' +
            '<div class="table-responsive"><table class="table table-sm align-middle"><thead>' +
            '<tr class="text-uppercase small text-muted"><th>Producto</th><th>Lote</th><th>Vencimiento</th><th>Cant. merma</th><th>Límite de merma</th><th>Stock disponible</th></tr>' +
            '</thead><tbody>' + rowsHtml + '</tbody></table></div>';

        modalFooter.style.display = 'flex';
        if (isAdmin && w.status === 'PENDIENTE' && w.puede_resolver) {
            decisionButtons.style.display = 'flex';
        } else {
            decisionButtons.style.display = 'none';
        }
        confirmButtons.style.display = 'none';
        rejectReasonWrap.style.display = 'none';
        btnRejectModal.style.display = '';
        btnConfirmApprove.style.display = 'inline-block';
        btnConfirmReject.style.display = 'none';
    }

    function openConfirmDecision(tipo, bodyHtml, reason) {
        currentWaste._pending = { tipo: tipo, reason: reason || '' };
        pendingDecision = { tipo: tipo, reason: reason || '' };
        const esAprobar = (tipo === 'aprobar');

        approvalModalEl.classList.add('confirm-mode');
        document.body.classList.add('ph-confirm-blur');
        modalBody.style.display = 'none';
        confirmDecisionBody.style.display = '';
        confirmDecisionBody.innerHTML =
            '<div class="p-2">' +
            '<div class="confirm-badge mb-3"><i class="bi ' + (esAprobar ? 'bi-check-circle' : 'bi-x-circle') + '"></i>' +
            (esAprobar ? 'Confirmar aprobación' : 'Confirmar rechazo') + '</div>' +
            bodyHtml +
            '</div>';

        decisionButtons.style.display = 'none';
        rejectReasonWrap.style.display = 'none';
        confirmButtons.style.display = 'flex';

        btnConfirmDecisionOk.className = esAprobar ? 'btn btn-ph-success' : 'btn btn-danger';
        btnConfirmDecisionOk.innerHTML = esAprobar
            ? '<i class="bi bi-check-circle me-1"></i>Sí, aprobar'
            : '<i class="bi bi-check2-circle me-1"></i>Sí, rechazar';
    }

    // ---- Aprobar: abrir confirmación ----
    btnConfirmApprove.addEventListener('click', function () {
        if (!currentWaste) return;
        const w = currentWaste;
        openConfirmDecision(
            'aprobar',
            '<div class="fs-6 text-dark mb-2"><i class="bi bi-check-circle me-2" style="color:#0d8a43;"></i>¿Desea <b>aprobar</b> la merma <b>#' + w.id + '</b>?</div>' +
            '<div class="small text-muted border-top pt-2 mt-2">' +
            '<div><span class="fw-bold">Tipo:</span> ' + esc(w.type_name) + '</div>' +
            '<div><span class="fw-bold">Sede:</span> ' + esc(w.location_name) + '</div>' +
            '<div><span class="fw-bold">Cantidad:</span> ' + w.total_quantity + '</div>' +
            '<div class="mt-1 text-danger"><i class="bi bi-exclamation-triangle me-1"></i>Al aprobar se <b>descontará el stock</b> disponible en esta sede.</div></div>'
        );
    });

    // ---- Rechazar: mostrar motivo y confirmar ----
    btnRejectModal.addEventListener('click', function () {
        if (!currentWaste) return;
        rejectReasonWrap.style.display = 'block';
        rejectReasonError.style.display = 'none';
        btnRejectModal.style.display = 'none';
        btnConfirmApprove.style.display = 'none';
        btnConfirmReject.style.display = 'inline-block';
    });

    btnConfirmReject.addEventListener('click', function () {
        if (!currentWaste) return;
        const reason = rejectReason.value.trim();
        rejectReasonError.style.display = 'none';
        if (reason.length < 15) {
            rejectReasonError.textContent = 'El motivo debe tener al menos 15 caracteres (actual: ' + reason.length + ').';
            rejectReasonError.style.display = 'block';
            return;
        }
        const w = currentWaste;
        openConfirmDecision(
            'rechazar',
            '<div class="fs-6 text-dark mb-2"><i class="bi bi-x-circle me-2" style="color:#af1515;"></i>¿Desea <b>rechazar</b> la merma <b>#' + w.id + '</b>?</div>' +
            '<div class="small text-muted border-top pt-2 mt-2">' +
            '<div><span class="fw-bold">Tipo:</span> ' + esc(w.type_name) + '</div>' +
            '<div><span class="fw-bold">Sede:</span> ' + esc(w.location_name) + '</div>' +
            '<div><span class="fw-bold">Cantidad:</span> ' + w.total_quantity + '</div>' +
            '<div class="mt-2"><span class="fw-bold">Motivo:</span> <span class="text-dark">' + esc(reason) + '</span></div>' +
            '<div class="mt-1" style="color:#0d8a43;"><i class="bi bi-info-circle me-1"></i>Al rechazar <b>no se tocará el stock</b>.</div></div>',
            reason
        );
    });

    // ---- Volver (desde la vista de confirmación al detalle) ----
    btnConfirmCancel.addEventListener('click', function () {
        if (!currentWaste) return;
        pendingDecision = null;
        currentWaste._pending = null;
        fillDetail(currentWaste);
    });

    // ---- Confirmar (botón Sí, continuar) ----
    btnConfirmDecisionOk.addEventListener('click', async function () {
        if (!pendingDecision || !currentWaste) return;
        const btn = this;
        btn.disabled = true;
        try {
            let res;
            if (pendingDecision.tipo === 'aprobar') {
                res = await fetch('/api/waste/merma/' + currentWaste.id + '/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({})
                });
            } else {
                res = await fetch('/api/waste/merma/' + currentWaste.id + '/reject', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ reason: pendingDecision.reason })
                });
            }
            const data = await res.json();
            if (data.success) {
                pendingDecision = null;
                approvalModal.hide();
                showAlert(data.message, false);
                await loadPending();
            } else {
                const e = data.errors ? Object.values(data.errors)[0] : (data.message || 'No se pudo completar la acción.');
                showAlert(e, true);
            }
        } catch (err) {
            showAlert('Error de conexión al procesar la decisión.', true);
        } finally {
            btn.disabled = false;
        }
    });

    if (searchInput) searchInput.addEventListener('input', applySearchFilter);

    loadPending();
});
