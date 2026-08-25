document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("receptionForm");
    const movementId = form ? form.dataset.movementId : null;
    const destinationName = form ? form.dataset.destinationName : "Destino";
    
    const rows = document.querySelectorAll(".item-row");
    const noveltySelect = document.getElementById("noveltyType");
    const noveltyHelpText = document.getElementById("noveltyHelpText");
    const notesRequiredFlag = document.getElementById("notesRequiredFlag");
    const notesTextarea = document.getElementById("receptionNotes");
    const btnSubmit = document.getElementById("btnSubmitReception");
    const alertBox = document.getElementById("receptionAlertBox");
    const noveltyStatusBadge = document.getElementById("noveltyStatusBadge");

    const confirmModal = document.getElementById("confirmModal");
    const confirmModalText = document.getElementById("confirmModalText");
    const btnCancelModal = document.getElementById("btnCancelModal");
    const btnAcceptModal = document.getElementById("btnAcceptModal");

    let userManuallyChangedNovelty = false;

    const NOVELTY_GUIDES = {
        CONFORME: {
            help: "Carga completa y en condiciones óptimas. Se acredita en destino.",
            placeholder: "Observaciones generales de recepción (opcional)..."
        },
        FALTANTE_CONTEO: {
            help: "Descuadre físico menor a la guía. La diferencia quedará congelada en tránsito para arbitraje.",
            placeholder: "Indique la cantidad faltante verificada con el transportista..."
        },
        SOBRANTE_EXCEDENTE: {
            help: "Carga física superior a la autorizada. El excedente se resguarda sin ingresar a inventario.",
            placeholder: "Detalle la cantidad excedente y si los empaques venían identificados..."
        },
        PRODUCTO_ERRONEO: {
            help: "Insumo físico no corresponde a la orden. No ingresa a estantería y se resguarda para retorno.",
            placeholder: "Describa el producto o SKU que llegó físicamente en lugar del solicitado..."
        },
        VIOLACION_CUSTODIA: {
            help: "Precintos rotos o bultos forzados. Se inicia investigación sobre la empresa de transporte.",
            placeholder: "Especifique números de precintos rotos o anomalías del transportista..."
        },
        INCIDENCIA_TEMPERATURA: {
            help: "Ruptura de cadena de frío. La carga asienta y debe darse de baja en Módulo 7 con fotografía.",
            placeholder: "Registre la temperatura medida en muelle (°C)..."
        },
        VENCIMIENTO_PROXIMO: {
            help: "Lote con vida útil reducida. Se notifica a cocina para priorizar su consumo inmediato.",
            placeholder: "Detalle la fecha física de caducidad observada en los empaques..."
        },
        LOTE_NO_COINCIDE: {
            help: "El número de lote impreso difiere del registrado en la guía digital.",
            placeholder: "Indique el serial de lote exacto que viene impreso en el empaque..."
        },
        RECHAZO_POR_ESPACIO: {
            help: "Cava o depósito sin espacio suficiente. El remanente regresa en el camión a Central.",
            placeholder: "Indique la cantidad que permanece en el camión por falta de espacio..."
        }
    };

    function showAlert(message) {
        alertBox.textContent = message;
        alertBox.classList.remove("hidden");
    }

    function hideAlert() {
        alertBox.classList.add("hidden");
    }

    function updateNoveltyGuidance(novelty) {
        const info = NOVELTY_GUIDES[novelty] || NOVELTY_GUIDES.CONFORME;
        noveltyHelpText.textContent = info.help;
        notesTextarea.placeholder = info.placeholder;
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
        let shortageItems = [];

        rows.forEach(row => {
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const diffBadge = row.querySelector(".diff-badge");
            const unit = row.dataset.unit || "";
            const productName = row.dataset.product || "Insumo";
            
            let received = parseFloat(input.value);
            if (isNaN(received) || received < 0) {
                received = 0;
            }

            const diff = received - dispatched;

            diffBadge.className = "diff-badge";
            row.classList.remove("row-ok", "row-missing", "row-surplus");

            if (Math.abs(diff) < 0.001) {
                diffBadge.classList.add("diff-ok");
                diffBadge.textContent = "0.00";
                row.classList.add("row-ok");
            } else if (diff < 0) {
                hasShortage = true;
                shortageItems.push(`${productName} (${Math.abs(diff).toFixed(2)} ${unit})`);
                diffBadge.classList.add("diff-missing");
                diffBadge.textContent = diff.toFixed(2);
                row.classList.add("row-missing");
            } else {
                hasSurplus = true;
                diffBadge.classList.add("diff-surplus");
                diffBadge.textContent = `+${diff.toFixed(2)}`;
                row.classList.add("row-surplus");
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

        updateNoveltyGuidance(noveltySelect.value);

        noveltyStatusBadge.className = "status-pill";
        if (hasShortage) {
            noveltyStatusBadge.classList.add("pill-missing");
            noveltyStatusBadge.textContent = "Faltante detectado";
            btnSubmit.textContent = "Confirmar con Discrepancia";
            btnSubmit.className = "btn-ph-primary btn-alert-state";
        } else if (hasSurplus) {
            noveltyStatusBadge.classList.add("pill-surplus");
            noveltyStatusBadge.textContent = "Sobrante en muelle";
            btnSubmit.textContent = "Confirmar con Sobrante";
            btnSubmit.className = "btn-ph-primary btn-alert-state";
        } else {
            noveltyStatusBadge.classList.add("pill-ok");
            noveltyStatusBadge.textContent = "Conforme (Cuadrado)";
            btnSubmit.textContent = "Confirmar y Asentar Stock";
            btnSubmit.className = "btn-ph-primary";
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
        hideAlert();
        updateNoveltyGuidance(noveltySelect.value);
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

        const { hasShortage, hasSurplus, hasNumericDiscrepancy } = updateDifferences();
        const noveltyType = noveltySelect.value;
        const notes = notesTextarea.value.trim();

        if (hasSurplus && noveltyType !== "SOBRANTE_EXCEDENTE") {
            showAlert("Existe un excedente físico de mercancía. La clasificación principal debe ser 'Sobrante / Excedente en Muelle'.");
            noveltySelect.focus();
            return;
        }

        if (hasShortage && noveltyType !== "FALTANTE_CONTEO" && noveltyType !== "RECHAZO_POR_ESPACIO") {
            showAlert("Existe un faltante físico de stock. La clasificación principal debe ser 'Faltante de Conteo' (detalle cualquier anomalía cualitativa en las notas).");
            noveltySelect.focus();
            return;
        }

        if (!hasNumericDiscrepancy && (noveltyType === "FALTANTE_CONTEO" || noveltyType === "SOBRANTE_EXCEDENTE")) {
            showAlert("Las cantidades están cuadradas al 100%. No puede registrar un faltante o sobrante numérico.");
            noveltySelect.focus();
            return;
        }

        if (noveltyType !== "CONFORME" && notes.length < 5) {
            showAlert("Debe ingresar una justificación detallada en las notas de muelle (mínimo 5 caracteres).");
            notesTextarea.focus();
            return;
        }

        if (noveltyType !== "CONFORME") {
            confirmModalText.textContent = `Se registrará este traslado con la novedad '${noveltyType}'. La carga conforme ingresará al inventario disponible de ${destinationName} y cualquier discrepancia quedará congelada en tránsito para arbitraje administrativo. ¿Desea asentar el stock?`;
        } else {
            confirmModalText.textContent = `¿Certifica que el cargamento llegó completo, con precintos intactos y en óptimas condiciones para ingresar al inventario de ${destinationName}?`;
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
            const rawVal = parseFloat(row.querySelector(".input-received").value);
            const receivedQty = isNaN(rawVal) || rawVal < 0 ? 0 : rawVal;
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
                showAlert(result.message || "Ocurrió un error al procesar la recepción.");
                btnSubmit.disabled = false;
                btnSubmit.textContent = "Confirmar y Asentar Stock";
            }
        } catch (error) {
            showAlert("Error de conexión al procesar el traslado.");
            btnSubmit.disabled = false;
            btnSubmit.textContent = "Confirmar y Asentar Stock";
        }
    });

    updateDifferences();
});