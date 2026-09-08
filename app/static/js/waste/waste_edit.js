document.addEventListener("DOMContentLoaded", function () {
    const alertsBox = document.getElementById("editAlerts");
    const wasteIdInput = document.getElementById("wasteId");
    if (!wasteIdInput) return;
    const wasteId = wasteIdInput.value;

    function showAlert(message, isError) {
        if (!alertsBox) return;
        alertsBox.innerHTML = "";
        const div = document.createElement("div");
        div.className = "alert " + (isError ? "alert-danger" : "alert-success") + " alert-dismissible fade show border-0 shadow-sm";
        div.innerHTML = (isError ? '<i class="bi bi-exclamation-triangle-fill me-2"></i>' : '<i class="bi bi-check-circle-fill me-2"></i>') +
            message + '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';
        alertsBox.appendChild(div);
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    /* ============ Regla de vencimiento (tipo VENCIDO) ============ */
    const editLocationIdInput = document.getElementById("editLocationId");
    const editLocationId = editLocationIdInput ? editLocationIdInput.value : "";
    let vencidosByProduct = null;

    async function loadVencidos() {
        vencidosByProduct = {};
        if (!editLocationId) return;
        try {
            const data = await (await fetch("/api/waste/locations/" + editLocationId + "/vencidos")).json();
            if (data.success) {
                (data.vencidos || []).forEach(function (v) {
                    const pid = String(v.product_id);
                    if (!vencidosByProduct[pid]) vencidosByProduct[pid] = [];
                    vencidosByProduct[pid].push({
                        lot_number: String(v.lot_number),
                        quantity: v.quantity,
                        expiration_date: v.expiration_date
                    });
                });
            }
        } catch (e) {
            vencidosByProduct = {};
        }
    }

    function restoreLotOptions(row) {
        const select = row.querySelector(".ph-select-lot");
        if (!select) return;
        const all = row._allLotOptions || Array.from(select.options);
        select.innerHTML = "";
        all.forEach(function (o) { select.appendChild(o.cloneNode(true)); });
    }

    async function applyVencidoFilter(row, updateFn) {
        const typeSelect = row.querySelector(".ph-select-type");
        const select = row.querySelector(".ph-select-lot");
        if (!typeSelect || !select) return;

        const opt = typeSelect.options[typeSelect.selectedIndex];
        const isVencido = opt && opt.dataset.code === "VENCIDO";

        if (!isVencido) {
            restoreLotOptions(row);
            if (updateFn) updateFn();
            return;
        }

        if (!vencidosByProduct) await loadVencidos();

        const pid = String(row.dataset.productId);
        const venSet = new Set((vencidosByProduct[pid] || []).map(function (v) { return String(v.lot_number); }));
        const keepLot = select.value;
        const all = row._allLotOptions || Array.from(select.options);
        const allowed = all.filter(function (o) { return venSet.has(String(o.value)); });

        select.innerHTML = "";
        allowed.forEach(function (o) { select.appendChild(o.cloneNode(true)); });

        if (allowed.some(function (o) { return String(o.value) === String(keepLot); })) {
            select.value = keepLot;
        } else if (keepLot) {
            const optActual = document.createElement("option");
            optActual.value = keepLot;
            optActual.dataset.exp = row.dataset.exp || "";
            optActual.dataset.stock = "0";
            optActual.textContent = keepLot + " (actual)";
            select.appendChild(optActual);
            select.value = keepLot;
        } else if (allowed.length) {
            select.value = allowed[0].value;
        }

        if (updateFn) updateFn();
    }

    function setupRowLotAndQty(row) {
        const select = row.querySelector(".ph-select-lot");
        const qtyInput = row.querySelector(".line-qty");
        const expDisplay = row.querySelector(".line-exp-display");
        const stockValDisplay = row.querySelector(".lot-stock-val");
        const typeSelect = row.querySelector(".ph-select-type");

        function updateFromSelectedLot() {
            if (!select) return;
            const opt = select.options[select.selectedIndex];
            if (!opt) return;

            const expDate = opt.dataset.exp || "";
            const availableStock = parseFloat(opt.dataset.stock) || 0;

            row.dataset.lot = select.value;
            row.dataset.exp = expDate;
            row.dataset.maxStock = availableStock;

            if (expDisplay) {
                expDisplay.textContent = expDate ? expDate : "N/A";
            }
            if (stockValDisplay) {
                stockValDisplay.textContent = availableStock;
            }

            if (qtyInput) {
                qtyInput.max = availableStock;
                clampQuantity(qtyInput, availableStock);
            }
        }

        if (select) {
            row._allLotOptions = Array.from(select.options);
            select.addEventListener("change", updateFromSelectedLot);
        }

        if (typeSelect) {
            typeSelect.addEventListener("change", function () {
                applyVencidoFilter(row, updateFromSelectedLot);
            });
            const curOpt = typeSelect.options[typeSelect.selectedIndex];
            if (curOpt && curOpt.dataset.code === "VENCIDO") {
                applyVencidoFilter(row, updateFromSelectedLot);
            }
        }

        if (qtyInput) {
            qtyInput.addEventListener("input", function () {
                const maxStock = parseFloat(row.dataset.maxStock) || 0;
                clampQuantity(this, maxStock);
            });

            qtyInput.addEventListener("blur", function () {
                const maxStock = parseFloat(row.dataset.maxStock) || 0;
                clampQuantity(this, maxStock);
            });
        }
    }

    function clampQuantity(input, maxStock) {
        let val = parseFloat(input.value);
        if (isNaN(val)) return;

        if (maxStock > 0 && val > maxStock) {
            input.value = maxStock;
            input.classList.add("is-invalid");
            setTimeout(function () {
                input.classList.remove("is-invalid");
            }, 800);
        } else if (val < 0) {
            input.value = "0.01";
        }
    }

    /* ============ Fotos editables por ítem ============ */
    function uploadToEvidence(file) {
        return new Promise(function (resolve) {
            const formData = new FormData();
            formData.append("image", file);
            fetch("/api/waste/evidence", { method: "POST", body: formData })
                .then(function (res) { return res.json(); })
                .then(function (result) {
                    if (result && result.success && result.url) resolve(result.url);
                    else {
                        showAlert("Una foto no se pudo cargar; puede continuar sin ella.", true);
                        resolve(null);
                    }
                })
                .catch(function () {
                    showAlert("Error de conexión al subir una foto; puede continuar sin ella.", true);
                    resolve(null);
                });
        });
    }

    function renderLinePhotos(cell, photosArr) {
        if (!cell) return;
        cell.innerHTML = "";
        const wrap = document.createElement("div");
        wrap.className = "ph-photo-edit-wrap";

        (photosArr || []).forEach(function (url) {
            const box = document.createElement("div");
            box.className = "ph-photo-edit-item";
            const img = document.createElement("img");
            img.src = url;
            img.title = "Ver foto";
            img.addEventListener("click", function () { window.open(url, "_blank"); });
            const del = document.createElement("button");
            del.type = "button";
            del.title = "Quitar esta foto";
            del.className = "btn ph-photo-edit-del";
            del.innerHTML = '<i class="bi bi-x"></i>';
            del.addEventListener("click", function () {
                const i = photosArr.indexOf(url);
                if (i !== -1) photosArr.splice(i, 1);
                renderLinePhotos(cell, photosArr);
            });
            box.appendChild(img);
            box.appendChild(del);
            wrap.appendChild(box);
        });

        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.title = "Subir foto";
        addBtn.className = "btn btn-outline-primary ph-photo-add";
        addBtn.innerHTML = '<i class="bi bi-plus-lg"></i>';
        const fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.accept = "image/*";
        fileInput.className = "d-none";
        fileInput.addEventListener("change", function () {
            const file = fileInput.files && fileInput.files[0];
            if (!file) return;
            if (!file.type || !file.type.startsWith("image/")) {
                showAlert("Solo se permiten archivos de imagen.", true);
                return;
            }
            if ((photosArr || []).length >= 10) {
                showAlert("Máximo 10 fotos por producto.", true);
                return;
            }
            addBtn.disabled = true;
            addBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            uploadToEvidence(file).then(function (url) {
                addBtn.disabled = false;
                addBtn.innerHTML = '<i class="bi bi-plus-lg"></i>';
                if (url) {
                    photosArr.push(url);
                    renderLinePhotos(cell, photosArr);
                }
            });
        });
        addBtn.addEventListener("click", function () {
            if ((photosArr || []).length < 10) fileInput.click();
            else showAlert("Máximo 10 fotos por producto.", true);
        });
        wrap.appendChild(fileInput);
        wrap.appendChild(addBtn);
        cell.appendChild(wrap);
    }

    function setupRowPhotos(row) {
        const cell = row.querySelector(".ph-photo-cell");
        if (!cell || row.dataset.photosInited) return;
        row.dataset.photosInited = "1";
        let photos = [];
        try {
            const raw = row.dataset.photos;
            photos = raw ? JSON.parse(raw) : [];
        } catch (e) {
            photos = [];
        }
        row._linePhotos = photos.filter(function (u) { return typeof u === "string" && u; });
        renderLinePhotos(cell, row._linePhotos);
    }

    document.querySelectorAll("#editLinesTable tbody tr.line-row").forEach(function (row) {
        setupRowPhotos(row);
        setupRowLotAndQty(row);
    });

    function captureOriginalState() {
        const rows = document.querySelectorAll("#editLinesTable tbody tr.line-row");
        const lines = [];
        rows.forEach(function (row) {
            const lotSelect = row.querySelector(".ph-select-lot");
            const qtyInput = row.querySelector(".line-qty");
            const typeSelect = row.querySelector(".ph-select-type");
            lines.push({
                lot_number: lotSelect ? lotSelect.value.trim() : (row.dataset.lot || "").trim(),
                quantity: parseFloat(qtyInput ? qtyInput.value : "0"),
                waste_type_id: typeSelect ? parseInt(typeSelect.value, 10) : null,
                photos: (row._linePhotos || []).slice()
            });
        });
        return {
            notes: document.getElementById("wasteNotesInput").value.trim(),
            lines: lines
        };
    }

    const originalState = captureOriginalState();

    function hasPendingChanges(payload) {
        if ((payload.notes || "").trim() !== originalState.notes) return true;
        const orig = originalState.lines;
        if (payload.lines.length !== orig.length) return true;
        for (let i = 0; i < orig.length; i++) {
            const a = payload.lines[i];
            const b = orig[i];
            if (String(a.lot_number) !== String(b.lot_number)) return true;
            if (Math.abs((parseFloat(a.quantity) || 0) - (parseFloat(b.quantity) || 0)) > 1e-9) return true;
            if (Number(a.waste_type_id) !== Number(b.waste_type_id)) return true;
            if (JSON.stringify(a.evidence_urls || []) !== JSON.stringify(b.photos || [])) return true;
        }
        return false;
    }

    const btnSaveEdit = document.getElementById("btnSaveEdit");
    const confirmModalEl = document.getElementById("confirmEditModal");
    const confirmSummaryBox = document.getElementById("confirmEditSummary");
    const btnConfirmSaveEdit = document.getElementById("btnConfirmSaveEdit");

    function phEscapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
        });
    }

    let pendingPayload = null;

    function buildPendingPayload() {
        const notes = document.getElementById("wasteNotesInput").value.trim();
        const rows = document.querySelectorAll("#editLinesTable tbody tr.line-row");

        const lines = [];
        let hasError = false;

        rows.forEach(function (row) {
            const productId = row.dataset.productId;
            const lotSelect = row.querySelector(".ph-select-lot");
            const lotNumber = lotSelect ? lotSelect.value.trim() : (row.dataset.lot || "").trim();
            const expDate = row.dataset.exp || null;
            const unitCost = row.dataset.unitCost || "0";
            const maxStock = parseFloat(row.dataset.maxStock) || 0;
            const qtyInput = row.querySelector(".line-qty");
            const qty = parseFloat(qtyInput.value);
            const typeSelect = row.querySelector(".ph-select-type");
            const lineTypeId = typeSelect ? parseInt(typeSelect.value, 10) : null;
            const typeCode = typeSelect && typeSelect.options[typeSelect.selectedIndex]
                ? typeSelect.options[typeSelect.selectedIndex].dataset.code
                : "";

            if (typeCode === "VENCIDO") {
                const lotExp = lotSelect && lotSelect.options[lotSelect.selectedIndex]
                    ? lotSelect.options[lotSelect.selectedIndex].dataset.exp
                    : row.dataset.exp;
                const today = new Date();
                today.setHours(0, 0, 0, 0);
                const lotDate = lotExp ? new Date(lotExp + "T00:00:00") : null;
                if (!lotDate || isNaN(lotDate.getTime()) || lotDate >= today) {
                    if (lotSelect) lotSelect.classList.add("is-invalid");
                    hasError = true;
                    return;
                }
            }

            if (!lotNumber) {
                if (lotSelect) lotSelect.classList.add("is-invalid");
                hasError = true;
            } else if (lotSelect) {
                lotSelect.classList.remove("is-invalid");
            }

            if (isNaN(qty) || qty <= 0 || (maxStock > 0 && qty > maxStock)) {
                qtyInput.classList.add("is-invalid");
                hasError = true;
            } else {
                qtyInput.classList.remove("is-invalid");
            }

            lines.push({
                product_id: parseInt(productId, 10),
                lot_number: lotNumber,
                expiration_date: expDate,
                unit_cost: parseFloat(unitCost),
                waste_type_id: lineTypeId,
                quantity: qty,
                evidence_urls: row._linePhotos || []
            });
        });

        if (hasError) {
            showAlert("Verifique las líneas: con el tipo VENCIDO solo se pueden mermar lotes cuya fecha de vencimiento ya haya pasado, la cantidad debe ser mayor a cero y no puede superar el límite físico del lote.", true);
            return null;
        }

        return { notes: notes, lines: lines, rows: rows };
    }

    function renderConfirmSummary(payload) {
        if (!confirmSummaryBox) return;

        let totalQty = 0;
        let totalPhotos = 0;
        const rowsHtml = [];

        payload.rows.forEach(function (row, idx) {
            const line = payload.lines[idx];
            const prodEl = row.querySelector(".td-prod .fw-bold");
            const productName = prodEl ? prodEl.textContent.trim() : ("Producto #" + line.product_id);
            const typeSel = row.querySelector(".ph-select-type");
            const typeName = typeSel && typeSel.selectedIndex >= 0
                ? typeSel.options[typeSel.selectedIndex].text
                : "—";
            const typeCode = typeSel && typeSel.options[typeSel.selectedIndex]
                ? typeSel.options[typeSel.selectedIndex].dataset.code
                : "";
            const qty = parseFloat(line.quantity) || 0;
            const nPhotos = (line.evidence_urls && line.evidence_urls.length) ? line.evidence_urls.length : 0;

            totalQty += qty;
            totalPhotos += nPhotos;

            rowsHtml.push(
                '<tr>' +
                '<td class="fw-bold ph-summary-prod">' + phEscapeHtml(productName) + '</td>' +
                '<td><span class="ph-lot-chip">' + phEscapeHtml(line.lot_number) + '</span></td>' +
                '<td class="text-center fw-bold">' + qty + '</td>' +
                '<td><span class="ph-type-badge' + (typeCode === "VENCIDO" ? " ph-type-vencido" : "") + '">' + phEscapeHtml(typeName) + '</span></td>' +
                '<td class="text-center">' +
                (nPhotos
                    ? '<span class="ph-photo-count"><i class="bi bi-camera me-1"></i>' + nPhotos + '</span>'
                    : '<span class="text-muted small">—</span>') +
                '</td>' +
                '</tr>'
            );
        });

        const statHtml =
            '<div class="ph-confirm-stats">' +
            '<div class="ph-confirm-stat"><i class="bi bi-box-seam ph-confirm-stat-icon"></i>' +
            '<span class="ph-confirm-stat-value">' + payload.rows.length + '</span>' +
            '<span class="ph-confirm-stat-label">Productos</span></div>' +
            '<div class="ph-confirm-stat"><i class="bi bi-sort-numeric-down ph-confirm-stat-icon"></i>' +
            '<span class="ph-confirm-stat-value">' + totalQty + '</span>' +
            '<span class="ph-confirm-stat-label">Unidades mermadas</span></div>' +
            '<div class="ph-confirm-stat"><i class="bi bi-camera ph-confirm-stat-icon"></i>' +
            '<span class="ph-confirm-stat-value">' + totalPhotos + '</span>' +
            '<span class="ph-confirm-stat-label">Fotos adjuntas</span></div>' +
            '</div>';

        const noteHtml = payload.notes
            ? '<div class="ph-summary-note"><i class="bi bi-chat-left-text me-2"></i>' +
              '<span class="fw-semibold">Motivo / Observaciones:</span> ' + phEscapeHtml(payload.notes) + '</div>'
            : '<div class="ph-summary-note"><i class="bi bi-chat-left-text me-2"></i>' +
              '<span class="fw-semibold">Motivo / Observaciones:</span> <span class="text-muted">Sin observaciones.</span></div>';

        const tableHtml =
            '<div class="ph-summary-table-wrap">' +
            '<table class="table table-sm align-middle mb-0 ph-summary-table">' +
            '<thead class="text-uppercase small text-muted"><tr>' +
            '<th>Producto</th><th>Lote</th><th class="text-center">Cant.</th><th>Motivo</th><th class="text-center">Fotos</th>' +
            '</tr></thead><tbody>' + rowsHtml.join("") +
            '<tr class="ph-summary-footer"><td colspan="2" class="fw-bold">Totales</td>' +
            '<td class="text-center fw-bold">' + totalQty + '</td>' +
            '<td></td>' +
            '<td class="text-center">' + totalPhotos + '</td>' +
            '</tr></tbody></table></div>';

        confirmSummaryBox.innerHTML = statHtml + tableHtml + noteHtml;
    }

    if (btnSaveEdit && confirmModalEl && confirmSummaryBox && btnConfirmSaveEdit) {
        btnSaveEdit.addEventListener("click", function () {
            const payload = buildPendingPayload();
            if (!payload) return;
            if (!hasPendingChanges(payload)) {
                showAlert("No realizaste ningún cambio. Realiza una modificación o vuelve dejando la merma en su estado inicial.", true);
                return;
            }
            pendingPayload = payload;
            const wasteIdTitle = document.getElementById("confirmEditWasteId");
            if (wasteIdTitle) wasteIdTitle.textContent = "#" + wasteId;
            renderConfirmSummary(payload);
            bootstrap.Modal.getOrCreateInstance(confirmModalEl).show();
        });

        btnConfirmSaveEdit.addEventListener("click", async function () {
            if (!pendingPayload) return;
            const payload = pendingPayload;
            btnConfirmSaveEdit.disabled = true;
            btnConfirmSaveEdit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Guardando...';

            try {
                const response = await fetch("/api/waste/merma/" + wasteId + "/edit", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    body: JSON.stringify({
                        notes: payload.notes,
                        lines: payload.lines
                    })
                });

                const data = await response.json();
                if (bootstrap.Modal.getInstance(confirmModalEl)) {
                    bootstrap.Modal.getInstance(confirmModalEl).hide();
                }
                if (response.ok && data.success) {
                    showAlert(data.message || "Merma actualizada correctamente.", false);
                    setTimeout(function () {
                        window.location.href = "/waste/merma/mis-pendientes";
                    }, 1200);
                } else {
                    const msg = data.message || (data.errors ? Object.values(data.errors)[0] : "Error al guardar cambios.");
                    showAlert(msg, true);
                }
            } catch (err) {
                if (bootstrap.Modal.getInstance(confirmModalEl)) {
                    bootstrap.Modal.getInstance(confirmModalEl).hide();
                }
                showAlert("Error de comunicación con el servidor al actualizar la merma.", true);
            } finally {
                btnConfirmSaveEdit.disabled = false;
                btnConfirmSaveEdit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Confirmar y Guardar';
                pendingPayload = null;
            }
        });
    }

    const revertModalEl = document.getElementById("revertModal");
    const btnOpenRevertModal = document.getElementById("btnOpenRevertModal");
    const btnConfirmRevert = document.getElementById("btnConfirmRevert");
    const revertReasonInput = document.getElementById("revertReasonInput");
    const revertCharCount = document.getElementById("revertCharCount");
    const revertReasonError = document.getElementById("revertReasonError");

    let revertModal = null;
    if (revertModalEl) {
        revertModal = bootstrap.Modal.getOrCreateInstance(revertModalEl);
    }

    if (btnOpenRevertModal && revertModal) {
        btnOpenRevertModal.addEventListener("click", function () {
            revertReasonInput.value = "";
            revertCharCount.textContent = "0 / 15 caracteres mínimos";
            revertCharCount.className = "text-muted small";
            revertReasonError.style.display = "none";
            btnConfirmRevert.disabled = true;
            revertModal.show();
        });
    }

    if (revertReasonInput && btnConfirmRevert) {
        revertReasonInput.addEventListener("input", function () {
            const val = revertReasonInput.value.trim();
            revertCharCount.textContent = val.length + " / 15 caracteres mínimos";
            if (val.length >= 15) {
                btnConfirmRevert.disabled = false;
                revertCharCount.className = "text-success small fw-bold";
                revertReasonError.style.display = "none";
            } else {
                btnConfirmRevert.disabled = true;
                revertCharCount.className = "text-danger small";
            }
        });

        btnConfirmRevert.addEventListener("click", async function () {
            const reason = revertReasonInput.value.trim();
            if (reason.length < 15) {
                revertReasonError.textContent = "El motivo debe tener al menos 15 caracteres.";
                revertReasonError.style.display = "block";
                return;
            }

            btnConfirmRevert.disabled = true;
            btnConfirmRevert.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Revirtiendo...';

            try {
                const response = await fetch("/api/waste/merma/" + wasteId + "/revert", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    body: JSON.stringify({ reason: reason })
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    revertModal.hide();
                    showAlert(data.message, false);
                    setTimeout(function () {
                        window.location.reload();
                    }, 1200);
                } else {
                    const msg = data.message || (data.errors ? Object.values(data.errors)[0] : "No se pudo revertir la merma.");
                    revertReasonError.textContent = msg;
                    revertReasonError.style.display = "block";
                    btnConfirmRevert.disabled = false;
                    btnConfirmRevert.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Confirmar y Restituir Stock';
                }
            } catch (err) {
                revertReasonError.textContent = "Error al comunicarse con el servidor.";
                revertReasonError.style.display = "block";
                btnConfirmRevert.disabled = false;
                btnConfirmRevert.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Confirmar y Restituir Stock';
            }
        });
    }
});