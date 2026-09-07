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

    function setupRowLotAndQty(row) {
        const select = row.querySelector(".ph-select-lot");
        const qtyInput = row.querySelector(".line-qty");
        const expDisplay = row.querySelector(".line-exp-display");
        const stockValDisplay = row.querySelector(".lot-stock-val");

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
            select.addEventListener("change", updateFromSelectedLot);
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

    document.querySelectorAll("#editLinesTable tbody tr.line-row").forEach(setupRowLotAndQty);

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
                quantity: qty
            });
        });

        if (hasError) {
            showAlert("Verifique las líneas: la cantidad debe ser mayor a cero y no puede superar el límite físico del lote.", true);
            return null;
        }

        return { notes: notes, lines: lines, rows: rows };
    }

    function renderConfirmSummary(payload) {
        if (!confirmSummaryBox) return;

        let html = '';

        if (payload.notes) {
            html += '<div class="mb-3">' +
                '<span class="small fw-bold text-muted d-block">Motivo / Observaciones</span>' +
                '<div class="p-2 rounded-3 bg-light border small">' + phEscapeHtml(payload.notes) + '</div></div>';
        }

        html += '<div class="table-responsive rounded-3 border">' +
            '<table class="table table-sm align-middle mb-0">' +
            '<thead class="text-uppercase small text-muted" style="background:#f8f9fa;">' +
            '<tr><th>Producto</th><th>Lote</th><th class="text-center">Cantidad</th><th>Tipo de Merma</th></tr>' +
            '</thead><tbody>';

        payload.rows.forEach(function (row, idx) {
            const line = payload.lines[idx];
            const prodEl = row.querySelector(".td-prod .fw-bold");
            const productName = prodEl ? prodEl.textContent.trim() : ("Producto #" + line.product_id);
            const typeSel = row.querySelector(".ph-select-type");
            const typeName = typeSel && typeSel.selectedIndex >= 0
                ? typeSel.options[typeSel.selectedIndex].text
                : "—";
            html += '<tr>' +
                '<td class="fw-bold">' + phEscapeHtml(productName) + '</td>' +
                '<td>' + phEscapeHtml(line.lot_number) + '</td>' +
                '<td class="text-center fw-bold">' + line.quantity + '</td>' +
                '<td>' + phEscapeHtml(typeName) + '</td></tr>';
        });

        html += '</tbody></table></div>';
        confirmSummaryBox.innerHTML = html;
    }

    if (btnSaveEdit && confirmModalEl && confirmSummaryBox && btnConfirmSaveEdit) {
        btnSaveEdit.addEventListener("click", function () {
            const payload = buildPendingPayload();
            if (!payload) return;
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