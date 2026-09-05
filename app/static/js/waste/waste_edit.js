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
    if (btnSaveEdit) {
        btnSaveEdit.addEventListener("click", async function () {
            const wasteTypeId = document.getElementById("wasteTypeSelect").value;
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
                    quantity: qty
                });
            });

            if (hasError) {
                showAlert("Verifique las líneas: la cantidad debe ser mayor a cero y no puede superar el límite físico del lote.", true);
                return;
            }

            btnSaveEdit.disabled = true;
            btnSaveEdit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Guardando...';

            try {
                const response = await fetch("/api/waste/merma/" + wasteId + "/edit", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest"
                    },
                    body: JSON.stringify({
                        waste_type_id: wasteTypeId,
                        notes: notes,
                        lines: lines
                    })
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    showAlert(data.message || "Merma actualizada correctamente.", false);
                    setTimeout(function () {
                        window.location.href = "/waste/merma/pending";
                    }, 1000);
                } else {
                    const msg = data.message || (data.errors ? Object.values(data.errors)[0] : "Error al guardar cambios.");
                    showAlert(msg, true);
                    btnSaveEdit.disabled = false;
                    btnSaveEdit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Guardar Modificaciones';
                }
            } catch (err) {
                showAlert("Error de comunicación con el servidor al actualizar la merma.", true);
                btnSaveEdit.disabled = false;
                btnSaveEdit.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Guardar Modificaciones';
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