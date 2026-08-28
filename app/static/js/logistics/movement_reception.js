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

    const dynamicGuideBox = document.getElementById("dynamicProtocolGuideBox");
    const protocolGuideTitle = document.getElementById("protocolGuideTitle");
    const protocolGuideBody = document.getElementById("protocolGuideBody");

    const erroneousSection = document.getElementById("erroneousProductSection");
    const erroneousItemsList = document.getElementById("erroneousItemsList");
    const btnAddErroneousItem = document.getElementById("btnAddErroneousItem");
    const catalogOptionsTemplate = document.getElementById("catalogOptionsTemplate")?.innerHTML || "";

    const confirmModal = document.getElementById("confirmModal");
    const confirmModalContent = document.getElementById("confirmModalContent");
    const btnCancelModal = document.getElementById("btnCancelModal");
    const btnAcceptModal = document.getElementById("btnAcceptModal");

    let userManuallyChangedNovelty = false;

    const NOVELTY_TITLES = {
        CONFORME: "Recepción Conforme al 100%",
        FALTANTE_CONTEO: "Faltante Físico de Conteo",
        SOBRANTE_EXCEDENTE: "Excedente / Sobrante en Muelle",
        PRODUCTO_ERRONEO: "Producto Erróneo / SKU Cruzado",
        INCIDENCIA_TEMPERATURA: "Ruptura de Cadena de Frío",
        VENCIMIENTO_PROXIMO: "Alerta de Vencimiento Próximo",
        LOTE_NO_COINCIDE: "Lote no coincide con Guía",
        VIOLACION_CUSTODIA: "Violación de Custodia (Precinto Roto)",
        RECHAZO_POR_ESPACIO: "Rechazo Parcial por Falta de Espacio",
        INCIDENCIA_MIXTA: "Incidencia Mixta (Múltiples Novedades)"
    };

    const PROTOCOL_GUIDES = {
        CONFORME: {
            theme: "card-ok-guide",
            icon: "bi-check-circle-fill",
            title: "Protocolo Operativo: Recepción Conforme",
            body: "Todos los renglones coinciden exactamente con la orden digital. La totalidad de los insumos ingresará de inmediato al disponible operativo de la sede.",
            buttonText: "Confirmar y Asentar Stock",
            buttonAlert: false,
            help: "Carga completa y en condiciones óptimas. Se acredita en destino."
        },
        FALTANTE_CONTEO: {
            theme: "card-missing-guide",
            icon: "bi-exclamation-triangle-fill",
            title: "Protocolo Obligatorio: Faltante de Conteo Físico",
            body: `<ul>
                <li><strong>Instrucción en Tabla:</strong> Coloque en «Recibido Conforme» la cantidad exacta que ingresó a bodega.</li>
                <li><strong>Retención Contable:</strong> La diferencia faltante quedará inmovilizada en tránsito de la sede emisora para investigación de muelle y arbitraje.</li>
                <li><strong>Justificación:</strong> Indique en las notas el conteo verificado junto con el transportista.</li>
            </ul>`,
            buttonText: "Confirmar con Faltante",
            buttonAlert: true,
            help: "Descuadre físico menor a la guía. La diferencia quedará congelada en tránsito para arbitraje."
        },
        SOBRANTE_EXCEDENTE: {
            theme: "card-surplus-guide",
            icon: "bi-box-seam-fill",
            title: "Protocolo Obligatorio: Sobrante / Excedente Físico",
            body: `<ul>
                <li><strong>Instrucción en Tabla:</strong> Coloque en «Recibido Conforme» la cantidad física total descargada (superior a la orden).</li>
                <li><strong>Resguardo Preventivo:</strong> El sistema acreditará la cantidad autorizada en la orden. El excedente físico permanecerá en resguardo temporal sin ingresar a producción.</li>
                <li><strong>Justificación:</strong> Detalle en las notas el número de bultos o cajas adicionales recibidas.</li>
            </ul>`,
            buttonText: "Confirmar con Sobrante",
            buttonAlert: true,
            help: "Carga física superior a la autorizada. El excedente se resguarda sin ingresar a inventario."
        },
        PRODUCTO_ERRONEO: {
            theme: "card-missing-guide",
            icon: "bi-exclamation-octagon-fill",
            title: "Protocolo Obligatorio: Producto Erróneo / SKU Cruzado",
            body: `<ul>
                <li><strong>Paso 1 (Tabla superior):</strong> Si el producto solicitado en la guía no llegó físicamente, coloque <strong>0.00</strong> en «Recibido Conforme» para generar el faltante formal.</li>
                <li><strong>Paso 2 (Formulario inferior):</strong> Declare los insumos físicos descargados por error del camión seleccionándolos del catálogo.</li>
                <li><strong>Custodia:</strong> La mercancía no solicitada permanecerá en <strong>custodia física temporal</strong> para coordinar su retorno formal a Central.</li>
            </ul>`,
            buttonText: "Confirmar Producto Erróneo",
            buttonAlert: true,
            help: "Insumo físico no corresponde a la orden. Indique el insumo entregado y resguárdelo para retorno."
        },
        INCIDENCIA_TEMPERATURA: {
            theme: "card-warning-guide",
            icon: "bi-thermometer-high",
            title: "Protocolo Obligatorio: Ruptura de Cadena de Frío",
            body: `<ul>
                <li><strong>Certificación de Entrega:</strong> Se asienta la recepción de la carga física para cerrar la responsabilidad del flete con el transportista.</li>
                <li><strong>Baja por Descarte Sanitario:</strong> Diríjase a <strong>Traslados y Mermas -> Gestión de Mermas</strong> en el menú lateral para dar de baja los productos descompuestos con su evidencia fotográfica.</li>
                <li><strong>Justificación:</strong> Registre en las notas la temperatura en grados (°C) medida en muelle y los empaques afectados.</li>
            </ul>`,
            buttonText: "Confirmar con Incidencia Térmica",
            buttonAlert: true,
            help: "Ruptura de cadena de frío. La descarga se certifica y los insumos dañados deben registrarse en Gestión de Mermas."
        },
        VENCIMIENTO_PROXIMO: {
            theme: "card-warning-guide",
            icon: "bi-calendar-x-fill",
            title: "Protocolo Operativo: Lote con Vencimiento Próximo",
            body: `<ul>
                <li><strong>Ingreso Operativo:</strong> La mercancía ingresa normalmente a bodega.</li>
                <li><strong>Alerta Preventiva:</strong> Se emitirá una notificación interna a cocina para priorizar la rotación inmediata de este lote bajo el método FEFO.</li>
            </ul>`,
            buttonText: "Confirmar con Alerta FEFO",
            buttonAlert: true,
            help: "Lote con vida útil reducida. Se notifica a cocina para priorizar su consumo inmediato."
        },
        LOTE_NO_COINCIDE: {
            theme: "card-warning-guide",
            icon: "bi-upc-scan",
            title: "Protocolo Operativo: Lote no coincide con Guía",
            body: `<ul>
                <li><strong>Ingreso Físico:</strong> La mercancía física ingresa a bodega si el insumo corresponde.</li>
                <li><strong>Captura de Lote Real:</strong> Escriba en la tabla superior el número de lote físico real impreso en los empaques recibidos.</li>
                <li><strong>Corrección Administrativa:</strong> La orden se escala a la Administración para actualizar la partida en la base de datos sin rechazar la carga.</li>
            </ul>`,
            buttonText: "Confirmar con Corrección de Lote",
            buttonAlert: true,
            help: "El número de lote impreso difiere del registrado en la guía digital. Ingrese el lote físico real."
        },
        VIOLACION_CUSTODIA: {
            theme: "card-warning-guide",
            icon: "bi-shield-slash-fill",
            title: "Protocolo Obligatorio: Violación de Custodia / Precintos",
            body: `<ul>
                <li><strong>Instrucción:</strong> Si el conteo físico coincide con la guía, la mercancía ingresa al disponible de la sucursal.</li>
                <li><strong>Auditoría de Seguridad:</strong> Se generará una alerta prioritaria en la bitácora para abrir una investigación sobre la empresa de transporte.</li>
                <li><strong>Justificación:</strong> Registre obligatoriamente la numeración de los precintos rotos o el estado de los empaques.</li>
            </ul>`,
            buttonText: "Confirmar con Alerta de Custodia",
            buttonAlert: true,
            help: "Precintos rotos o bultos forzados. Se inicia investigación sobre la empresa de transporte."
        },
        RECHAZO_POR_ESPACIO: {
            theme: "card-missing-guide",
            icon: "bi-box-arrow-left",
            title: "Protocolo Obligatorio: Rechazo Parcial por Falta de Espacio",
            body: `<ul>
                <li><strong>Instrucción en Tabla:</strong> Coloque en «Recibido Conforme» únicamente la cantidad que cabe en sus cavas/depósito.</li>
                <li><strong>Retorno de Emergencia:</strong> El remanente no descargado permanecerá en el camión para que el Administrador dicte el retorno a Central.</li>
            </ul>`,
            buttonText: "Confirmar Rechazo por Espacio",
            buttonAlert: true,
            help: "Cava o depósito sin espacio suficiente. El remanente regresa en el camión a Central."
        },
        INCIDENCIA_MIXTA: {
            theme: "card-warning-guide",
            icon: "bi-diagram-3-fill",
            title: "Protocolo Operativo: Incidencia Mixta (Múltiples Novedades)",
            body: `<ul>
                <li><strong>Ajuste Granular:</strong> Cada renglón de la tabla superior ha registrado su condición particular y diferencias de cantidad.</li>
                <li><strong>Insumos No Solicitados:</strong> Los productos declarados en la sección inferior permanecerán en custodia física temporal.</li>
                <li><strong>Escalamiento a Arbitraje:</strong> El Administrador resolverá de forma independiente el destino de cada ítem en la Bandeja de Arbitraje.</li>
            </ul>`,
            buttonText: "Confirmar Incidencias Mixtas",
            buttonAlert: true,
            help: "Múltiples condiciones detectadas en distintos renglones. Se generará un acta consolidada para arbitraje."
        }
    };

    function showAlert(message) {
        alertBox.textContent = message;
        alertBox.classList.remove("hidden");
    }

    function hideAlert() {
        alertBox.classList.add("hidden");
    }

    function addErroneousItemRow() {
        const rowDiv = document.createElement("div");
        rowDiv.className = "err-row-grid p-2 bg-white border rounded shadow-sm";
        rowDiv.innerHTML = `
            <div>
                <select class="form-select form-select-sm err-product-select" required>
                    ${catalogOptionsTemplate}
                </select>
            </div>
            <div>
                <input type="text" class="form-control form-control-sm bg-light font-monospace err-sku-display" placeholder="SKU" readonly>
            </div>
            <div>
                <div class="input-group input-group-sm">
                    <input type="number" step="0.01" min="0.01" class="form-control err-qty-input" placeholder="0.00" required>
                    <span class="input-group-text err-unit-tag">UN</span>
                </div>
            </div>
            <div class="text-center">
                <button type="button" class="btn btn-sm btn-outline-danger btn-remove-erroneous" title="Eliminar fila">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        `;

        const select = rowDiv.querySelector(".err-product-select");
        const skuDisplay = rowDiv.querySelector(".err-sku-display");
        const unitTag = rowDiv.querySelector(".err-unit-tag");
        const btnRemove = rowDiv.querySelector(".btn-remove-erroneous");

        select.addEventListener("change", function() {
            const opt = this.options[this.selectedIndex];
            if (opt) {
                skuDisplay.value = opt.dataset.sku || "";
                unitTag.textContent = opt.dataset.unit || "UN";
            }
        });

        btnRemove.addEventListener("click", function() {
            rowDiv.remove();
            checkAndAutoCategorize();
        });

        erroneousItemsList.appendChild(rowDiv);
        checkAndAutoCategorize();
    }

    if (btnAddErroneousItem) {
        btnAddErroneousItem.addEventListener("click", addErroneousItemRow);
    }

    function updateBadgeAndGuidance() {
        const novelty = noveltySelect.value;
        const guide = PROTOCOL_GUIDES[novelty] || PROTOCOL_GUIDES.CONFORME;

        noveltyHelpText.textContent = guide.help;
        dynamicGuideBox.className = `protocol-guide-box ${guide.theme} mt-3`;
        protocolGuideTitle.innerHTML = `<i class="bi ${guide.icon}"></i> ${guide.title}`;
        protocolGuideBody.innerHTML = guide.body;

        noveltyStatusBadge.className = "status-pill";

        if (novelty === "CONFORME") {
            noveltyStatusBadge.classList.add("pill-ok");
            noveltyStatusBadge.textContent = "Recepción Conforme";
        } else if (novelty === "FALTANTE_CONTEO") {
            noveltyStatusBadge.classList.add("pill-missing");
            noveltyStatusBadge.textContent = "Faltante de Conteo";
        } else if (novelty === "SOBRANTE_EXCEDENTE") {
            noveltyStatusBadge.classList.add("pill-surplus");
            noveltyStatusBadge.textContent = "Sobrante en Muelle";
        } else if (novelty === "PRODUCTO_ERRONEO") {
            noveltyStatusBadge.classList.add("pill-error-product");
            noveltyStatusBadge.textContent = "Producto Erróneo / SKU Cruzado";
        } else if (novelty === "LOTE_NO_COINCIDE") {
            noveltyStatusBadge.classList.add("pill-warning");
            noveltyStatusBadge.textContent = "Lote no coincide con Guía";
        } else if (novelty === "INCIDENCIA_MIXTA") {
            noveltyStatusBadge.classList.add("pill-warning");
            noveltyStatusBadge.textContent = "Incidencias Mixtas en Muelle";
        } else {
            noveltyStatusBadge.classList.add("pill-warning");
            noveltyStatusBadge.textContent = NOVELTY_TITLES[novelty] || "Incidencia Reportada";
        }

        btnSubmit.textContent = guide.buttonText;
        btnSubmit.className = guide.buttonAlert ? "btn-ph-primary btn-alert-state" : "btn-ph-primary";

        if (novelty === "PRODUCTO_ERRONEO" || novelty === "INCIDENCIA_MIXTA") {
            if (erroneousSection) {
                erroneousSection.classList.remove("hidden");
                if (erroneousItemsList && erroneousItemsList.children.length === 0 && novelty === "PRODUCTO_ERRONEO") {
                    addErroneousItemRow();
                }
            }
        } else {
            if (erroneousSection) {
                erroneousSection.classList.add("hidden");
                if (erroneousItemsList) {
                    erroneousItemsList.innerHTML = "";
                }
            }
        }
    }

    function checkAndAutoCategorize() {
        let hasShortage = false;
        let hasSurplus = false;
        let hasColdChain = false;
        let hasLotMismatch = false;
        let hasNearExp = false;
        let hasCustodyBreach = false;
        let hasSpaceRejection = false;
        let hasRowErroneous = false;
        let distinctIssuesCount = 0;

        rows.forEach(row => {
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const diffBadge = row.querySelector(".diff-badge");
            const condSelect = row.querySelector(".select-item-condition");
            const lotBox = row.querySelector(".row-lot-mismatch");
            
            let received = parseFloat(input.value);
            if (isNaN(received) || received < 0) received = 0;

            const diff = received - dispatched;
            const condition = condSelect ? condSelect.value : "CONFORME";

            if (lotBox) {
                if (condition === "LOTE_NO_COINCIDE") {
                    lotBox.classList.remove("hidden");
                } else {
                    lotBox.classList.add("hidden");
                }
            }

            diffBadge.className = "diff-badge";
            row.classList.remove("row-ok", "row-missing", "row-surplus", "row-warning");

            if (condition !== "CONFORME") {
                row.classList.add("row-warning");
                if (condition === "INCIDENCIA_TEMPERATURA") hasColdChain = true;
                if (condition === "LOTE_NO_COINCIDE") hasLotMismatch = true;
                if (condition === "VENCIMIENTO_PROXIMO") hasNearExp = true;
                if (condition === "VIOLACION_CUSTODIA") hasCustodyBreach = true;
                if (condition === "RECHAZO_POR_ESPACIO") hasSpaceRejection = true;
                if (condition === "PRODUCTO_ERRONEO") hasRowErroneous = true;
                if (condition === "FALTANTE_CONTEO") hasShortage = true;
                if (condition === "SOBRANTE_EXCEDENTE") hasSurplus = true;
            }

            if (Math.abs(diff) < 0.001) {
                diffBadge.classList.add("diff-ok");
                diffBadge.textContent = "0.00";
                if (condition === "CONFORME") row.classList.add("row-ok");
            } else if (diff < 0) {
                hasShortage = true;
                diffBadge.classList.add("diff-missing");
                diffBadge.textContent = diff.toFixed(2);
                if (condition === "CONFORME") row.classList.add("row-missing");
            } else {
                hasSurplus = true;
                diffBadge.classList.add("diff-surplus");
                diffBadge.textContent = `+${diff.toFixed(2)}`;
                if (condition === "CONFORME") row.classList.add("row-surplus");
            }
        });

        const hasUnsolicitedItems = document.querySelectorAll(".err-row-grid").length > 0 || hasRowErroneous;

        if (hasShortage) distinctIssuesCount++;
        if (hasSurplus) distinctIssuesCount++;
        if (hasColdChain) distinctIssuesCount++;
        if (hasLotMismatch) distinctIssuesCount++;
        if (hasNearExp) distinctIssuesCount++;
        if (hasCustodyBreach) distinctIssuesCount++;
        if (hasSpaceRejection) distinctIssuesCount++;
        if (hasUnsolicitedItems) distinctIssuesCount++;

        const hasAnyIssue = distinctIssuesCount > 0;

        if (!userManuallyChangedNovelty) {
            if (distinctIssuesCount > 1) {
                noveltySelect.value = "INCIDENCIA_MIXTA";
            } else if (hasUnsolicitedItems) {
                noveltySelect.value = "PRODUCTO_ERRONEO";
            } else if (hasSpaceRejection) {
                noveltySelect.value = "RECHAZO_POR_ESPACIO";
            } else if (hasShortage) {
                noveltySelect.value = "FALTANTE_CONTEO";
            } else if (hasSurplus) {
                noveltySelect.value = "SOBRANTE_EXCEDENTE";
            } else if (hasColdChain) {
                noveltySelect.value = "INCIDENCIA_TEMPERATURA";
            } else if (hasLotMismatch) {
                noveltySelect.value = "LOTE_NO_COINCIDE";
            } else if (hasNearExp) {
                noveltySelect.value = "VENCIMIENTO_PROXIMO";
            } else if (hasCustodyBreach) {
                noveltySelect.value = "VIOLACION_CUSTODIA";
            } else {
                noveltySelect.value = "CONFORME";
            }
        }

        updateBadgeAndGuidance();

        if (hasAnyIssue || noveltySelect.value !== "CONFORME") {
            notesRequiredFlag.classList.remove("hidden");
            notesTextarea.required = true;
        } else {
            notesRequiredFlag.classList.add("hidden");
            notesTextarea.required = false;
        }

        return { hasShortage, hasSurplus, hasAnyIssue, distinctIssuesCount };
    }

    noveltySelect.addEventListener("change", () => {
        userManuallyChangedNovelty = true;
        hideAlert();
        updateBadgeAndGuidance();
        const { hasAnyIssue } = checkAndAutoCategorize();
        if (noveltySelect.value !== "CONFORME" || hasAnyIssue) {
            notesRequiredFlag.classList.remove("hidden");
            notesTextarea.required = true;
        } else {
            notesRequiredFlag.classList.add("hidden");
            notesTextarea.required = false;
        }
    });

    rows.forEach(row => {
        const input = row.querySelector(".input-received");
        const condSelect = row.querySelector(".select-item-condition");

        input.addEventListener("input", () => {
            hideAlert();
            checkAndAutoCategorize();
        });

        if (condSelect) {
            condSelect.addEventListener("change", () => {
                hideAlert();
                if (condSelect.value === "PRODUCTO_ERRONEO") {
                    input.value = "0.00";
                    if (erroneousSection) {
                        erroneousSection.classList.remove("hidden");
                        if (erroneousItemsList && erroneousItemsList.children.length === 0) {
                            addErroneousItemRow();
                        }
                    }
                }
                checkAndAutoCategorize();
            });
        }
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        hideAlert();

        const { hasAnyIssue } = checkAndAutoCategorize();
        const noveltyType = noveltySelect.value;
        const readableTitle = NOVELTY_TITLES[noveltyType] || "Recepción de Mercancía";
        const notes = notesTextarea.value.trim();

        if (hasAnyIssue && notes.length < 5) {
            showAlert("Debe ingresar una justificación detallada en las notas de muelle (mínimo 5 caracteres).");
            notesTextarea.focus();
            return;
        }

        const itemsPayload = [];
        let missingLotField = false;

        rows.forEach(row => {
            const detailId = parseInt(row.dataset.detailId);
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const condSelect = row.querySelector(".select-item-condition");
            const lotInput = row.querySelector(".input-row-lot");

            let receivedQty = parseFloat(input.value);
            if (isNaN(receivedQty) || receivedQty < 0) receivedQty = 0;

            const condition = condSelect ? condSelect.value : "CONFORME";
            const observedLot = (lotInput && condition === "LOTE_NO_COINCIDE") ? lotInput.value.trim() : null;

            if (condition === "LOTE_NO_COINCIDE" && !observedLot) {
                missingLotField = true;
            }

            itemsPayload.push({
                detail_id: detailId,
                product_name: row.dataset.product,
                sku: row.dataset.sku,
                unit: row.dataset.unit,
                dispatched_qty: dispatched,
                received_quantity: receivedQty,
                item_condition: condition,
                observed_physical_lot: observedLot
            });
        });

        if (missingLotField) {
            showAlert("Debe ingresar el lote físico real impreso en el empaque para el insumo marcado con Lote no coincide.");
            return;
        }

        const erroneousPayload = [];
        let errInvalid = false;
        
        if (noveltyType === "PRODUCTO_ERRONEO" || noveltyType === "INCIDENCIA_MIXTA") {
            document.querySelectorAll(".err-row-grid").forEach(er => {
                const sel = er.querySelector(".err-product-select");
                const qtyInput = er.querySelector(".err-qty-input");
                const prodId = parseInt(sel.value);
                const qty = parseFloat(qtyInput.value);

                if (prodId && qty > 0) {
                    erroneousPayload.push({
                        product_id: prodId,
                        product_name: sel.options[sel.selectedIndex].text,
                        quantity: qty,
                        unit: sel.options[sel.selectedIndex].dataset.unit || "UN"
                    });
                } else {
                    errInvalid = true;
                }
            });

            if (noveltyType === "PRODUCTO_ERRONEO" && erroneousPayload.length === 0) {
                showAlert("Debe declarar al menos un insumo físico entregado por error.");
                return;
            }

            if (errInvalid) {
                showAlert("Complete todos los campos del insumo no solicitado con cantidades válidas mayores a cero.");
                return;
            }
        }

        let modalHtml = `<p class="modal-lead-text">Se certificará la descarga en <strong>${destinationName}</strong> bajo la condición: <strong>${readableTitle}</strong></p>`;
        let listItemsHtml = "";

        itemsPayload.forEach(it => {
            const diff = it.received_quantity - it.dispatched_qty;
            let conditionTag = `<span class="badge bg-success">Conforme</span>`;

            if (it.item_condition === "INCIDENCIA_TEMPERATURA") {
                conditionTag = `<span class="badge bg-danger">Ruptura Cadena Frío</span>`;
            } else if (it.item_condition === "LOTE_NO_COINCIDE") {
                conditionTag = `<span class="badge bg-warning text-dark">Lote Real: ${it.observed_physical_lot}</span>`;
            } else if (it.item_condition === "VENCIMIENTO_PROXIMO") {
                conditionTag = `<span class="badge bg-info text-dark">Vencimiento Próximo</span>`;
            } else if (it.item_condition === "VIOLACION_CUSTODIA") {
                conditionTag = `<span class="badge bg-danger">Empaque Dañado</span>`;
            } else if (it.item_condition === "RECHAZO_POR_ESPACIO") {
                conditionTag = `<span class="badge bg-danger">Rechazo por Espacio</span>`;
            } else if (it.item_condition === "PRODUCTO_ERRONEO") {
                conditionTag = `<span class="badge bg-danger">Producto Erróneo</span>`;
            } else if (it.item_condition === "FALTANTE_CONTEO") {
                conditionTag = `<span class="badge bg-danger">Faltante Físico</span>`;
            } else if (it.item_condition === "SOBRANTE_EXCEDENTE") {
                conditionTag = `<span class="badge bg-primary">Sobrante Físico</span>`;
            }

            let diffText = `<span class="text-success">0.00 ${it.unit}</span>`;
            if (diff < -0.001) {
                diffText = `<span class="text-danger fw-bold">${diff.toFixed(2)} ${it.unit} (Faltante)</span>`;
            } else if (diff > 0.001) {
                diffText = `<span class="text-primary fw-bold">+${diff.toFixed(2)} ${it.unit} (Sobrante)</span>`;
            }

            listItemsHtml += `
                <li class="modal-breakdown-item">
                    <div>
                        <strong>${it.product_name}</strong> (${it.received_quantity.toFixed(2)} / ${it.dispatched_qty.toFixed(2)} ${it.unit})
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        ${diffText}
                        ${conditionTag}
                    </div>
                </li>
            `;
        });

        erroneousPayload.forEach(ep => {
            listItemsHtml += `
                <li class="modal-breakdown-item bg-light">
                    <div><strong>${ep.product_name}</strong> (No Solicitado)</div>
                    <span class="text-danger fw-bold">${ep.quantity.toFixed(2)} ${ep.unit} (En Resguardo)</span>
                </li>
            `;
        });

        modalHtml += `
            <div class="modal-status-card ${hasAnyIssue ? 'card-warning' : 'card-ok'}">
                <div class="card-title"><i class="bi ${hasAnyIssue ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill'}"></i> Resumen de Descarga Renglón por Renglón:</div>
                <ul class="modal-breakdown-list">${listItemsHtml}</ul>
            </div>
            <div class="modal-note-box">
                <strong>Declaración asentada en muelle:</strong> "${notes || 'Recepción conforme sin observaciones adicionales'}"
            </div>
        `;

        confirmModalContent.innerHTML = modalHtml;
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
            const input = row.querySelector(".input-received");
            const condSelect = row.querySelector(".select-item-condition");
            const lotInput = row.querySelector(".input-row-lot");

            let receivedQty = parseFloat(input.value);
            if (isNaN(receivedQty) || receivedQty < 0) receivedQty = 0;

            const condition = condSelect ? condSelect.value : "CONFORME";
            const observedLot = (lotInput && condition === "LOTE_NO_COINCIDE") ? lotInput.value.trim() : null;

            itemsPayload.push({
                detail_id: detailId,
                received_quantity: receivedQty,
                item_condition: condition,
                observed_physical_lot: observedLot
            });
        });

        const erroneousPayload = [];
        if (noveltyType === "PRODUCTO_ERRONEO" || noveltyType === "INCIDENCIA_MIXTA") {
            document.querySelectorAll(".err-row-grid").forEach(er => {
                const sel = er.querySelector(".err-product-select");
                const qtyInput = er.querySelector(".err-qty-input");
                const prodId = parseInt(sel.value);
                const qty = parseFloat(qtyInput.value);
                if (prodId && qty > 0) {
                    erroneousPayload.push({
                        product_id: prodId,
                        quantity: qty
                    });
                }
            });
        }

        btnSubmit.disabled = true;
        btnSubmit.textContent = "Procesando...";

        try {
            const response = await fetch(`/logistics/movements/reception/${movementId}/process`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    novelty_type: noveltyType,
                    notes: notes,
                    items: itemsPayload,
                    erroneous_products: erroneousPayload
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                window.location.href = result.redirect_url || "/logistics/movements";
            } else {
                showAlert(result.message || "Error al procesar la recepción.");
                btnSubmit.disabled = false;
                btnSubmit.textContent = "Confirmar y Asentar Stock";
            }
        } catch (error) {
            showAlert("Error de conexión al procesar el traslado.");
            btnSubmit.disabled = false;
            btnSubmit.textContent = "Confirmar y Asentar Stock";
        }
    });

    checkAndAutoCategorize();
});