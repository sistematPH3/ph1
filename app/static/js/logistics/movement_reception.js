document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("receptionForm");
    const movementId = form ? form.dataset.movementId : null;
    const rows = document.querySelectorAll(".item-row");
    const noveltySelect = document.getElementById("noveltyType");
    const notesRequiredFlag = document.getElementById("notesRequiredFlag");
    const notesTextarea = document.getElementById("receptionNotes");
    const btnSubmit = document.getElementById("btnSubmitReception");
    const alertBox = document.getElementById("receptionAlertBox");

    const confirmModal = document.getElementById("confirmModal");
    const confirmModalText = document.getElementById("confirmModalText");
    const btnCancelModal = document.getElementById("btnCancelModal");
    const btnAcceptModal = document.getElementById("btnAcceptModal");

    let userManuallyChangedNovelty = false;

    function showAlert(message, type = "error") {
        alertBox.className = `alert-box alert-${type}`;
        alertBox.textContent = message;
        alertBox.classList.remove("hidden");
    }

    function hideAlert() {
        alertBox.classList.add("hidden");
    }

    function setNotesRequired(isRequired) {
        if (isRequired) {
            notesRequiredFlag.classList.remove("hidden");
            notesTextarea.required = true;
        } else {
            notesRequiredFlag.classList.add("hidden");
            notesTextarea.required = false;
        }
    }

    function updateDifferences() {
        let hasShortage = false;
        let hasSurplus = false;

        rows.forEach(row => {
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const diffBadge = row.querySelector(".diff-badge");
            const received = parseFloat(input.value) || 0;
            const diff = received - dispatched;

            diffBadge.className = "diff-badge";

            if (Math.abs(diff) < 0.001) {
                diffBadge.classList.add("diff-ok");
                diffBadge.textContent = "0.00";
            } else if (diff < 0) {
                hasShortage = true;
                diffBadge.classList.add("diff-missing");
                diffBadge.textContent = diff.toFixed(2);
            } else {
                hasSurplus = true;
                diffBadge.classList.add("diff-surplus");
                diffBadge.textContent = `+${diff.toFixed(2)}`;
            }
        });

        const hasNumericDiscrepancy = hasShortage || hasSurplus;

        if (!userManuallyChangedNovelty) {
            if (hasShortage) {
                noveltySelect.value = "FALTANTE_CONTEO";
            } else if (hasSurplus) {
                noveltySelect.value = "SOBRANTE_EXCEDENTE";
            } else {
                noveltySelect.value = "CONFORME";
            }
        }

        if (noveltySelect.value !== "CONFORME" || hasNumericDiscrepancy) {
            setNotesRequired(true);
        } else {
            setNotesRequired(false);
        }

        return { hasShortage, hasSurplus, hasNumericDiscrepancy };
    }

    noveltySelect.addEventListener("change", () => {
        userManuallyChangedNovelty = true;
        if (noveltySelect.value !== "CONFORME") {
            setNotesRequired(true);
        } else {
            const { hasNumericDiscrepancy } = updateDifferences();
            if (!hasNumericDiscrepancy) {
                setNotesRequired(false);
            }
        }
    });

    rows.forEach(row => {
        const input = row.querySelector(".input-received");
        input.addEventListener("input", () => {
            hideAlert();
            updateDifferences();
        });
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        hideAlert();

        const { hasNumericDiscrepancy } = updateDifferences();
        const noveltyType = noveltySelect.value;
        const notes = notesTextarea.value.trim();

        if (hasNumericDiscrepancy && noveltyType === "CONFORME") {
            showAlert("Existe una diferencia numérica en las cantidades. Debe seleccionar un tipo de novedad distinto a 'Conforme'.", "error");
            noveltySelect.focus();
            return;
        }

        if (noveltyType !== "CONFORME" && notes.length < 5) {
            showAlert("Debe ingresar una justificación en las notas de muelle (mínimo 5 caracteres).", "error");
            notesTextarea.focus();
            return;
        }

        if (noveltyType !== "CONFORME") {
            confirmModalText.textContent = `Se registrará este traslado con la novedad '${noveltyType}'. La carga conforme ingresará a almacén y la discrepancia quedará inmovilizada en tránsito para arbitraje. ¿Desea continuar?`;
        } else {
            confirmModalText.textContent = "¿Confirma que el cargamento llegó completo y en óptimas condiciones para asentar en el inventario?";
        }

        confirmModal.classList.remove("hidden");
    });

    btnCancelModal.addEventListener("click", () => {
        confirmModal.classList.add("hidden");
    });

    btnAcceptModal.addEventListener("click", async () => {
        confirmModal.classList.add("hidden");

        const noveltyType = noveltySelect.value;
        const notes = notesTextarea.value.trim();

        const itemsPayload = [];
        rows.forEach(row => {
            const detailId = parseInt(row.dataset.detailId);
            const receivedQty = parseFloat(row.querySelector(".input-received").value) || 0;
            itemsPayload.push({
                detail_id: detailId,
                received_quantity: receivedQty
            });
        });

        btnSubmit.disabled = true;
        btnSubmit.textContent = "Procesando...";

        try {
            const response = await fetch(`/logistics/movements/reception/${movementId}/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    novelty_type: noveltyType,
                    notes: notes,
                    items: itemsPayload
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                window.location.href = result.redirect_url || "/logistics/movements";
            } else {
                showAlert(result.message || "Ocurrió un error al procesar la recepción.", "error");
                btnSubmit.disabled = false;
                btnSubmit.textContent = "Confirmar y Asentar Stock";
            }
        } catch (error) {
            console.error("Error:", error);
            showAlert("Error de conexión al procesar el traslado.", "error");
            btnSubmit.disabled = false;
            btnSubmit.textContent = "Confirmar y Asentar Stock";
        }
    });

    updateDifferences();
});