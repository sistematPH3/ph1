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
    const btnShowErroneous = document.getElementById("btnShowErroneous");
    const catalogOptionsTemplate = document.getElementById("catalogOptionsTemplate")?.innerHTML || "";

    const confirmModal = document.getElementById("confirmModal");
    const confirmModalContent = document.getElementById("confirmModalContent");
    const btnCancelModal = document.getElementById("btnCancelModal");
    const btnAcceptModal = document.getElementById("btnAcceptModal");

    let userManuallyChangedNovelty = false;
    let pendingReception = null;

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
        if (alertBox) {
            // El servidor devuelve una lista de errores; se unen legibles en vez de
            // dejar que un arreglo se convierta a texto plano con comas pegadas.
            const text = Array.isArray(message) ? message.join(" ") : String(message);
            alertBox.textContent = text;
            alertBox.classList.remove("hidden");
            alertBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    }

    function hideAlert() {
        if (alertBox) {
            alertBox.classList.add("hidden");
        }
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
            <div class="err-lot-exp w-100">
                <div class="input-group input-group-sm mt-1">
                    <span class="input-group-text" title="Lote físico real del insumo no solicitado">Lote</span>
                    <input type="text" class="form-control err-lot-input font-monospace" placeholder="Lote real en empaque...">
                </div>
                <div class="input-group input-group-sm mt-1">
                    <span class="input-group-text" title="Fecha de vencimiento del lote">Venc.</span>
                    <input type="date" class="form-control err-exp-input font-monospace" placeholder="AAAA-MM-DD">
                </div>
                <div class="err-exp-hint mt-1"></div>
            </div>
        `;

        const select = rowDiv.querySelector(".err-product-select");
        const skuDisplay = rowDiv.querySelector(".err-sku-display");
        const unitTag = rowDiv.querySelector(".err-unit-tag");
        const btnRemove = rowDiv.querySelector(".btn-remove-erroneous");
        const lotInput = rowDiv.querySelector(".err-lot-input");

        select.addEventListener("change", function() {
            const opt = this.options[this.selectedIndex];
            if (opt) {
                skuDisplay.value = opt.dataset.sku || "";
                unitTag.textContent = opt.dataset.unit || "UN";
            }
            handleErroneousLotLookup(rowDiv);
        });

        lotInput.addEventListener("input", () => {
            hideAlert();
            handleErroneousLotLookup(rowDiv);
        });

        btnRemove.addEventListener("click", function() {
            rowDiv.remove();
            checkAndAutoCategorize();
        });

        erroneousItemsList.appendChild(rowDiv);
        checkAndAutoCategorize();
    }

    function handleErroneousLotLookup(rowDiv) {
        const select = rowDiv.querySelector(".err-product-select");
        const lotInput = rowDiv.querySelector(".err-lot-input");
        const expInput = rowDiv.querySelector(".err-exp-input");
        const hint = rowDiv.querySelector(".err-exp-hint");

        const productId = parseInt(select.value);
        const lot = lotInput.value.trim();

        if (!productId || !lot) {
            if (expInput) expInput.value = "";
            if (hint) hint.innerHTML = "";
            return;
        }

        const url = `/logistics/movements/reception/lot-expiration?product_id=${encodeURIComponent(productId)}&lot_number=${encodeURIComponent(lot)}`;

        fetch(url, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        })
            .then(res => res.json().catch(() => ({})))
            .then(data => {
                if (!data || !data.success) {
                    expInput.value = "";
                    if (hint) hint.innerHTML = "";
                    expInput.dataset.verified = "";
                    return;
                }
                if (data.exists === false) {
                    expInput.value = "";
                    expInput.dataset.verified = "";
                    if (hint) {
                        hint.className = "err-exp-hint";
                        hint.innerHTML = `
                            <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1">
                                <i class="bi bi-search me-1"></i> Este registro de lote no se encuentra en el sistema
                            </span>`;
                    }
                    return;
                }
                if (data.expiration_date) {
                    expInput.value = data.expiration_date;
                    if (hint) {
                        hint.className = "err-exp-hint";
                        hint.innerHTML = `
                            <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle px-2 py-1">
                                <i class="bi bi-check-circle me-1"></i> Lote y vencimiento detectados
                            </span>`;
                    }
                    expInput.dataset.verified = "1";
                } else {
                    expInput.value = "";
                    expInput.dataset.verified = "";
                    if (hint) {
                        hint.className = "err-exp-hint";
                        hint.innerHTML = `
                            <span class="badge rounded-pill bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle px-2 py-1">
                                <i class="bi bi-check2 me-1"></i> Lote registrado, sin vencimiento conocido
                            </span>`;
                    }
                }
            })
            .catch(() => {
                expInput.value = "";
                if (hint) hint.innerHTML = "";
            });
    }


    if (btnAddErroneousItem) {
        btnAddErroneousItem.addEventListener("click", addErroneousItemRow);
    }

    // Botón siempre visible del panel "Diagnóstico y Justificación de Muelle".
    // Deja el acceso al registro de insumos entregados por error sin obligar al
    // operario a descubrir que debe elegir "Producto Erróneo" en el selector.
    function revealErroneousPanel() {
        if (erroneousSection) erroneousSection.classList.remove("hidden");
        if (erroneousItemsList && erroneousItemsList.children.length === 0) {
            addErroneousItemRow();
        }
        if (noveltySelect.value === "CONFORME") {
            noveltySelect.value = "PRODUCTO_ERRONEO";
            userManuallyChangedNovelty = true;
        }
        updateBadgeAndGuidance();
        if (noveltySelect.value !== "CONFORME") {
            notesRequiredFlag.classList.remove("hidden");
            notesTextarea.required = true;
        }
        if (erroneousItemsList) {
            const firstRow = erroneousItemsList.querySelector(".err-row-grid");
            if (firstRow) {
                firstRow.scrollIntoView({ behavior: "smooth", block: "center" });
                const firstSelect = firstRow.querySelector(".err-product-select");
                if (firstSelect) firstSelect.focus();
            }
        }
    }

    if (btnShowErroneous) {
        btnShowErroneous.addEventListener("click", revealErroneousPanel);
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

        // La declaración de insumos no solicitados (erróneos) se muestra cuando la
        // novedad es "Producto Erróneo"/"Incidencia Mixta" O mientras existan filas
        // ya cargadas. Nunca se vacían las filas al cambiar de novedad: el auto
        // diagnóstico re-deriva la clasificación con lo que ya está capturado.
        const hasErroneousRows = erroneousItemsList && erroneousItemsList.children.length > 0;
        const showUnsolicited = novelty === "PRODUCTO_ERRONEO" || novelty === "INCIDENCIA_MIXTA" || hasErroneousRows;
        if (erroneousSection) {
            if (showUnsolicited) {
                erroneousSection.classList.remove("hidden");
                if (!hasErroneousRows && novelty === "PRODUCTO_ERRONEO") {
                    addErroneousItemRow();
                }
            } else {
                erroneousSection.classList.add("hidden");
            }
        }
    }

    function updateLotExpiration(row, expiration, exists) {
        const expBox = row.querySelector(".lot-exp-lookup");
        const expInput = row.querySelector(".input-row-exp");
        const hint = row.querySelector(".lot-exp-hint");
        const lotInput = row.querySelector(".input-row-lot");

        if (!expBox || !expInput) return;

        const hasLot = lotInput && lotInput.value.trim().length > 0;

        if (hasLot) {
            expBox.classList.remove("hidden");
            if (exists === false) {
                expInput.value = "";
                expInput.dataset.verified = "";
                if (hint) {
                    hint.className = "lot-exp-hint mt-1";
                    hint.innerHTML = `
                        <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1">
                            <i class="bi bi-search me-1"></i> Este registro de lote no se encuentra en el sistema
                        </span>`;
                }
            } else if (expiration) {
                expInput.value = expiration;
                if (hint) {
                    hint.className = "lot-exp-hint mt-1";
                    hint.innerHTML = `
                        <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle px-2 py-1">
                            <i class="bi bi-check-circle me-1"></i> Vencimiento detectado del lote
                        </span>`;
                }
                expInput.dataset.verified = "1";
            } else {
                expInput.value = "";
                expInput.dataset.verified = "";
                if (hint) {
                    hint.className = "lot-exp-hint mt-1";
                    hint.innerHTML = `
                        <span class="badge rounded-pill bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle px-2 py-1">
                            <i class="bi bi-check2 me-1"></i> Lote registrado, sin vencimiento conocido
                        </span>`;
                }
            }
        } else {
            expBox.classList.add("hidden");
            expInput.value = "";
            expInput.dataset.verified = "";
        }
    }

    function handleLotLookup(row) {
        const productId = row.dataset.productId;
        const lotInput = row.querySelector(".input-row-lot");
        const lot = lotInput ? lotInput.value.trim() : "";

        if (!productId || !lot) {
            updateLotExpiration(row, null);
            return;
        }

        updateLotExpiration(row, null);

        const url = `/logistics/movements/reception/lot-expiration?product_id=${encodeURIComponent(productId)}&lot_number=${encodeURIComponent(lot)}`;

        fetch(url, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        })
            .then(res => res.json().catch(() => ({})))
            .then(data => {
                if (data && data.success) {
                    updateLotExpiration(row, data.expiration_date || null, data.exists);
                } else {
                    updateLotExpiration(row, null);
                }
            })
            .catch(() => updateLotExpiration(row, null));
    }

    function checkAndAutoCategorize(applyToSelect = true) {
        let rowsAffected = 0;
        let firstAffectedInfo = null;

        rows.forEach(row => {
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const diffBadge = row.querySelector(".diff-badge");
            const condSelect = row.querySelector(".select-item-condition");
            const lotBox = row.querySelector(".row-lot-mismatch");
            const lotExpBox = row.querySelector(".lot-exp-lookup");

            let received = parseFloat(input.value);
            if (isNaN(received) || received < 0) received = 0;

            const diff = received - dispatched;

            // Auto-clasificación de la CONDICIÓN del renglón (feedback de pruebas):
            // si el operario NO tocó el selector de condición, al tipear una cantidad
            // distinta la fila se etiqueta sola como "Me faltó / Me sobró"; si la
            // cantidad vuelve a coincidir se restaura a Conforme. Si el operario
            // eligió la condición manualmente, se respeta su decisión.
            const conditionWasManual = condSelect ? row.dataset.condManual === "1" : true;
            if (condSelect && !conditionWasManual) {
                if (diff < -0.001) condSelect.value = "FALTANTE_CONTEO";
                else if (diff > 0.001) condSelect.value = "SOBRANTE_EXCEDENTE";
                else condSelect.value = "CONFORME";
            }

            const condition = condSelect ? condSelect.value : "CONFORME";

            if (lotBox) {
                if (condition === "LOTE_NO_COINCIDE") {
                    lotBox.classList.remove("hidden");
                } else {
                    lotBox.classList.add("hidden");
                    if (lotExpBox) lotExpBox.classList.add("hidden");
                }
            }

            diffBadge.className = "diff-badge";
            row.classList.remove("row-ok", "row-missing", "row-surplus", "row-warning");

            const hasCondIssue = condition !== "CONFORME";
            const hasQtyIssue = Math.abs(diff) >= 0.001;
            if (hasCondIssue || hasQtyIssue) {
                rowsAffected++;
                if (!firstAffectedInfo) {
                    if (hasCondIssue) {
                        firstAffectedInfo = { kind: "CONDITION", condition };
                    } else {
                        firstAffectedInfo = { kind: "QTY", diff };
                    }
                }
            }

            if (Math.abs(diff) < 0.001) {
                diffBadge.classList.add("diff-ok");
                diffBadge.textContent = "0.00";
                if (condition === "CONFORME") row.classList.add("row-ok");
            } else if (diff < 0) {
                diffBadge.classList.add("diff-missing");
                diffBadge.textContent = diff.toFixed(2);
                row.classList.add("row-missing");
            } else {
                diffBadge.classList.add("diff-surplus");
                diffBadge.textContent = `+${diff.toFixed(2)}`;
                row.classList.add("row-surplus");
            }

            // Las condiciones de CALIDAD (temperatura, custodia, lote, espacio,
            // vencimiento) se resaltan en ámbar. Las diferencias de cantidad ya
            // tienen su borde rojo/azul, así que no hace falta otra clase.
            if (hasCondIssue &&
                condition !== "FALTANTE_CONTEO" &&
                condition !== "SOBRANTE_EXCEDENTE") {
                row.classList.add("row-warning");
            }
        });

        // Solo cuentan como insumos "no solicitados" las filas realmente completadas
        // (producto seleccionado + cantidad > 0). Una fila vacía agregada por error
        // no debe forzar la novedad PRODUCTO_ERRONEO ni bloquear una recepción que
        // por lo demás es conforme.
        const hasUnsolicitedItems = Array.from(document.querySelectorAll(".err-row-grid")).some(er => {
            const sel = er.querySelector(".err-product-select");
            const qtyInput = er.querySelector(".err-qty-input");
            const prodId = parseInt(sel ? sel.value : 0);
            const qty = qtyInput ? parseFloat(qtyInput.value) : NaN;
            return prodId > 0 && qty > 0;
        });

        const hasAnyIssue = rowsAffected > 0 || hasUnsolicitedItems;

        // REGLA (decisión de diseño): INCIDENCIA_MIXTA es SOLO cuando hay DOS o más
        // renglones afectados. Un único renglón con diferencia (con o sin erróneos)
        // NO es mixta: queda en la condición específica o en PRODUCTO_ERRONEO.
        let autoNovelty = "CONFORME";
        if (rowsAffected >= 2) {
            autoNovelty = "INCIDENCIA_MIXTA";
        } else if (hasUnsolicitedItems) {
            autoNovelty = "PRODUCTO_ERRONEO";
        } else if (rowsAffected === 1) {
            if (firstAffectedInfo.kind === "CONDITION") {
                autoNovelty = firstAffectedInfo.condition;
            } else {
                autoNovelty = firstAffectedInfo.diff < 0 ? "FALTANTE_CONTEO" : "SOBRANTE_EXCEDENTE";
            }
        }

        if (applyToSelect && !userManuallyChangedNovelty) {
            noveltySelect.value = autoNovelty;
        }

        updateBadgeAndGuidance();

        if (hasAnyIssue || noveltySelect.value !== "CONFORME") {
            notesRequiredFlag.classList.remove("hidden");
            notesTextarea.required = true;
        } else {
            notesRequiredFlag.classList.add("hidden");
            notesTextarea.required = false;
        }

        return { hasAnyIssue, rowsAffected, hasUnsolicitedItems, autoNovelty };
    }

    noveltySelect.addEventListener("change", () => {
        hideAlert();
        // Se captura la elección ANTES de cualquier re-derivación para que el
        // select inferior sea siempre seleccionable a mano ("el problema era el
        // lote entero": erróneo/faltante/sobrante global). El auto-diagnóstico
        // sigue activo mientras el operario NO elija y marca INCIDENCIA_MIXTA
        // automáticamente cuando hay dos o más novedades en los renglones.
        const chosen = noveltySelect.value;
        const result = checkAndAutoCategorize(false);
        const isManualChoice = chosen !== "CONFORME" && chosen !== result.autoNovelty;
        userManuallyChangedNovelty = isManualChoice;
        noveltySelect.value = isManualChoice ? chosen : result.autoNovelty;
        updateBadgeAndGuidance();
        if (noveltySelect.value !== "CONFORME" || result.hasAnyIssue) {
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
                row.dataset.condManual = "1";
                hideAlert();
                checkAndAutoCategorize();
            });
        }

        const lotInput = row.querySelector(".input-row-lot");
        if (lotInput) {
            lotInput.addEventListener("input", () => {
                hideAlert();
                handleLotLookup(row);
            });
        }
    });

    // Construcción ÚNICA del payload de la recepción: se usa para el resumen del modal
    // y ese MISMO objeto se reutiliza en el POST final, garantizando que se envíe
    // exactamente lo que se mostró (nada de reconstruirlo en el botón del modal).
    function buildReceptionPayload() {
        const items = [];
        let missingLotField = false;

        rows.forEach(row => {
            const detailId = parseInt(row.dataset.detailId);
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const condSelect = row.querySelector(".select-item-condition");
            const lotInput = row.querySelector(".input-row-lot");
            const expInput = row.querySelector(".input-row-exp");

            let receivedQty = parseFloat(input.value);
            if (isNaN(receivedQty) || receivedQty < 0) receivedQty = 0;

            const condition = condSelect ? condSelect.value : "CONFORME";
            const observedLot = (lotInput && condition === "LOTE_NO_COINCIDE") ? lotInput.value.trim() : null;

            if (condition === "LOTE_NO_COINCIDE" && !observedLot) {
                missingLotField = true;
            }

            items.push({
                detail_id: detailId,
                product_name: row.dataset.product,
                sku: row.dataset.sku,
                unit: row.dataset.unit,
                dispatched_qty: dispatched,
                received_quantity: receivedQty,
                item_condition: condition,
                observed_physical_lot: observedLot,
                observed_physical_expiration: (observedLot && expInput && expInput.value)
                    ? expInput.value
                    : null
            });
        });

        const erroneous = [];
        let errInvalid = false;

        document.querySelectorAll(".err-row-grid").forEach(er => {
            const sel = er.querySelector(".err-product-select");
            const qtyInput = er.querySelector(".err-qty-input");
            const lotInput = er.querySelector(".err-lot-input");
            const expInput = er.querySelector(".err-exp-input");
            const prodId = parseInt(sel.value);
            const qty = parseFloat(qtyInput.value);
            const qtyRaw = qtyInput.value.trim();

            // Una fila errónea totalmente vacía (producto sin elegir y sin cantidad)
            // se ignora: el sistema auto-agrega una fila al entrar a "Producto Erróneo"
            // para guiar al operario, pero esa fila vacía no debe bloquear el submit
            // cuando ya hay (al menos) un erróneo válido declarado.
            const isEmptyRow = !prodId && qtyRaw === "";

            if (prodId && qty > 0) {
                const lot = lotInput ? lotInput.value.trim() : "";
                erroneous.push({
                    product_id: prodId,
                    product_name: sel.options[sel.selectedIndex].text,
                    quantity: qty,
                    unit: sel.options[sel.selectedIndex].dataset.unit || "UN",
                    lot_number: lot || null,
                    expiration_date: (lot && expInput && expInput.value) ? expInput.value : null
                });
            } else if (!isEmptyRow) {
                errInvalid = true;
            }
        });

        return { items, erroneous, missingLotField, errInvalid };
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        hideAlert();

        const { hasAnyIssue, rowsAffected } = checkAndAutoCategorize();
        const noveltyType = noveltySelect.value;
        const notes = notesTextarea.value.trim();

        if (hasAnyIssue && notes.length < 5) {
            showAlert("Debe ingresar una justificación detallada en las notas de muelle (mínimo 5 caracteres).");
            notesTextarea.focus();
            return;
        }

        // Guard espejo del servidor: INCIDENCIA_MIXTA exige DOS o más renglones
        // afectados (regla de diseño). Con un solo renglón se bloquea antes de abrir
        // el modal; la auto-clasificación ya asigna la condición específica correcta.
        if (noveltyType === "INCIDENCIA_MIXTA" && rowsAffected < 2) {
            showAlert("La clasificación 'Incidencia Mixta' exige dos o más renglones afectados (condición o diferencia de cantidad). Si solo hubo un renglón con incidencia, use su clasificación específica.");
            return;
        }

        // Espejo del servidor: con dos o más renglones afectados además del
        // insumo no solicitado, el backend registra INCIDENCIA_MIXTA aunque el
        // selector diga PRODUCTO_ERRONEO (el modal mostraría algo que no se
        // asentaría igual). Se avisa antes de abrir la certificación.
        if (noveltyType === "PRODUCTO_ERRONEO" && rowsAffected >= 2) {
            showAlert("El sistema registrará esta recepción como 'Incidencia Mixta' porque hay dos o más renglones con incidencia y además un insumo no solicitado. Use la clasificación 'Incidencia Mixta' o deje un solo renglón afectado.");
            return;
        }

        // Guard de coherencia (espejo del servidor): una clasificación específica o
        // INCIDENCIA_MIXTA debe tener respaldo en algún renglón (condición o diferencia
        // de cantidad) o en erróneos. Si no, se bloquea antes de abrir el modal.
        const noveltyNeedsRowBacking = [
            "FALTANTE_CONTEO", "SOBRANTE_EXCEDENTE", "INCIDENCIA_TEMPERATURA",
            "LOTE_NO_COINCIDE", "VIOLACION_CUSTODIA", "RECHAZO_POR_ESPACIO",
            "INCIDENCIA_MIXTA"
        ].includes(noveltyType);
        if (noveltyNeedsRowBacking && !hasAnyIssue) {
            showAlert("La clasificación seleccionada no coincide con ningún renglón: no hay condición ni diferencia de cantidad que la respalde. Revise la tabla de insumos o cambie a 'Recepción Conforme'.");
            return;
        }

        const { items, erroneous, missingLotField, errInvalid } = buildReceptionPayload();
        const itemsPayload = items;
        const erroneousPayload = erroneous;

        if (missingLotField) {
            showAlert("Debe ingresar el lote físico real impreso en el empaque para el insumo marcado con Lote no coincide.");
            return;
        }

        if (noveltyType === "PRODUCTO_ERRONEO" && erroneousPayload.length === 0) {
            showAlert("Debe declarar al menos un insumo físico entregado por error.");
            return;
        }

        if (errInvalid) {
            showAlert("Complete todos los campos del insumo no solicitado con cantidades válidas mayores a cero.");
            return;
        }

        // Guarda el contenido exacto que se certificará; el botón del modal hará el
        // POST con ESTE payload (ya coherente con el auto-diagnóstico; solo una
        // decisión manual legítima lo desvía).
        pendingReception = {
            noveltyType,
            notes,
            items,
            erroneous
        };

        // Refleja la clasificación que efectivamente se enviará (coherente con filas
        // y erróneos tras el auto-diagnóstico; solo una decisión manual legítima la desvía).
        const effectiveTitle = NOVELTY_TITLES[noveltyType]
            || "Recepción de Mercancía";

        let modalHtml = `<p class="modal-lead-text">Se certificará la descarga en <strong>${destinationName}</strong> bajo la condición: <strong>${effectiveTitle}</strong></p>`;
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
            const lotInfo = ep.lot_number
                ? `<span class="text-muted small"> — Lote: ${ep.lot_number}${ep.expiration_date ? ` / Venc: ${ep.expiration_date}` : ""}</span>`
                : "";
            listItemsHtml += `
                <li class="modal-breakdown-item bg-light">
                    <div><strong>${ep.product_name}</strong> (No Solicitado)${lotInfo}</div>
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

        // Reutiliza el payload EXACTO guardado al abrir el modal: se envía lo mismo
        // que se mostró en el resumen (nada de reconstruirlo y arriesgar divergencias).
        if (!pendingReception) {
            showAlert("La recepción caducó. Revise la tabla e intente nuevamente.");
            return;
        }
        const payload = pendingReception;

        btnSubmit.disabled = true;
        btnSubmit.textContent = "Procesando...";

        try {
            const response = await fetch(`/logistics/movements/reception/${movementId}/process`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    novelty_type: payload.noveltyType,
                    notes: payload.notes,
                    items: payload.items,
                    erroneous_products: payload.erroneous
                })
            });

            // Captura robusta de la respuesta del servidor (sea éxito o error controlado)
            let result = {};
            try {
                result = await response.json();
            } catch (jsonErr) {
                console.error("La respuesta no devolvió un JSON válido:", jsonErr);
            }

            if (response.ok && result.success) {
                window.location.href = result.redirect_url || "/logistics/movements";
            } else {
                // AQUÍ ESTÁ LA CORRECCIÓN CLAVE: Extrae el mensaje de Python y lo pinta visiblemente en la interfaz
                const errorMessage = result.message || `Error del servidor (Código HTTP: ${response.status})`;
                showAlert(errorMessage);
                
                // Restaura el botón para permitir corregir y reintentar
                btnSubmit.disabled = false;
                updateBadgeAndGuidance();
            }
        } catch (error) {
            console.error("Error de red:", error);
            showAlert("Error de conexión al procesar el traslado con el servidor.");
            btnSubmit.disabled = false;
            updateBadgeAndGuidance();
        }
    });

    checkAndAutoCategorize();
});