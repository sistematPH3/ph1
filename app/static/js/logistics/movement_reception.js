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

    // Productos que YA vienen en la guía del traslado (renglones autorizados). Un
    // insumo que está en la guía nunca puede declararse como "entregado por error":
    // si va en la guía fue solicitado y, a lo sumo, puede estar completo, faltante o
    // sobrante. Se usa para bloquearlo como erróneo sin consultar al servidor.
    const manifestedProductIds = Array.from(rows).map(r => parseInt(r.dataset.productId, 10));

    // Stock físico actual del PRODUCTO en la sede ORIGEN (current_quantity). Se usa
    // como tope contra cantidades absurdas al declarar un insumo erróneo: el sistema
    // no lleva stock por lote, así que el único límite razonable es lo que el origen
    // conserva de ese producto. Proviene del atributo data-origin-stock de cada fila.
    const originStockMap = {};
    Array.from(rows).forEach(r => {
        const pid = parseInt(r.dataset.productId, 10);
        const stock = parseFloat(r.dataset.originStock);
        if (Number.isFinite(pid) && Number.isFinite(stock)) {
            originStockMap[pid] = stock;
        }
    });


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
                    <input type="number" step="0.01" min="0.01" max="1000000" class="form-control err-qty-input" placeholder="0.00" required>
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
                    <input type="date" class="form-control err-exp-input font-monospace" placeholder="AAAA-MM-DD" readonly>
                </div>
<div class="err-exp-hint mt-1"></div>
            </div>
            <div class="err-validation-hint d-none mt-1 w-100 small text-danger"></div>
        `;

        const select = rowDiv.querySelector(".err-product-select");
        const skuDisplay = rowDiv.querySelector(".err-sku-display");
        const unitTag = rowDiv.querySelector(".err-unit-tag");
        const btnRemove = rowDiv.querySelector(".btn-remove-erroneous");
        const lotInput = rowDiv.querySelector(".err-lot-input");
        const qtyInput = rowDiv.querySelector(".err-qty-input");
        const validationHint = rowDiv.querySelector(".err-validation-hint");

        select.addEventListener("change", function() {
            const opt = this.options[this.selectedIndex];
            if (opt) {
                skuDisplay.value = opt.dataset.sku || "";
                unitTag.textContent = opt.dataset.unit || "UN";
            }
            handleErroneousLotLookup(rowDiv);
            validateErroneousRow(rowDiv);
        });

        // Debounce para no lanzar un fetch por cada tecla al escribir el lote:
        // escribir "L-1000" disparaba hasta 6 consultas seguidas y ponía lenta la
        // página. Ahora solo consulta tras 300 ms de pausa de escritura.
        let erroneousLotDebounce = null;
        lotInput.addEventListener("input", () => {
            hideAlert();
            clearTimeout(erroneousLotDebounce);
            erroneousLotDebounce = setTimeout(() => {
                handleErroneousLotLookup(rowDiv);
                validateErroneousRow(rowDiv);
            }, 300);
        });

        qtyInput.addEventListener("input", () => validateErroneousRow(rowDiv));

        btnRemove.addEventListener("click", function() {
            rowDiv.remove();
            checkAndAutoCategorize();
            // Tras eliminar una fila duplicada, refrescar la validación de las restantes.
            document.querySelectorAll(".err-row-grid").forEach(vr => validateErroneousRow(vr));
        });

        erroneousItemsList.appendChild(rowDiv);
        checkAndAutoCategorize();
        validateErroneousRow(rowDiv);
    }

    // Valida una fila de insumo erróneo y muestra feedback inmediato (rojo) sin esperar
    // al submit. Chequea: (1) producto que ya viene en la guía, (2) cantidad que supera
    // el stock físico del producto en la sede ORIGEN (tope), (3) duplicados de
    // "producto + lote" contra otras filas erróneas. Cumple las reglas que ya aplica el
    // backend al guardar.
    function validateErroneousRow(rowDiv) {
        const select = rowDiv.querySelector(".err-product-select");
        const qtyInput = rowDiv.querySelector(".err-qty-input");
        const lotInput = rowDiv.querySelector(".err-lot-input");
        const hint = rowDiv.querySelector(".err-validation-hint");
        if (!select || !hint) return;

        // Tope de cordura absoluto: nunca se aceptan cantidades absurdas aunque el
        // origen no tenga inventario registrado o aún no llegue la consulta de stock.
        const MAX_ERRONEOUS_QTY = 1000000;

        const productId = select.value;
        const qty = parseFloat(qtyInput && qtyInput.value);
        const lot = (lotInput && lotInput.value || "").trim().toLowerCase();
        const messages = [];
        let isError = false;

        if (!productId) {
            select.classList.add("is-invalid");
        } else {
            select.classList.remove("is-invalid");
            // (1) Producto que ya viene en la guía no puede declararse como erróneo.
            if (manifestedProductIds.indexOf(parseInt(productId, 10)) > -1) {
                messages.push({
                    text: "Este producto YA viene en la guía; no puede declararse como erróneo.",
                    icon: "bi-x-octagon-fill",
                    kind: "danger"
                });
                select.classList.add("is-invalid");
                isError = true;
            }
            // (2) Tope de cordura absoluto: solo bloquea cantidades absurdas/irreales
            // (p. ej. 99999999999) sin comparar contra stock, para no confundir al
            // operario. El flujo de "disponible por lote" se decide aparte con Mariuska.
            if (qty && Number.isFinite(qty) && qty > MAX_ERRONEOUS_QTY) {
                messages.push({
                    text: `La cantidad (${qty}) es irreal para un insumo recibido por error.`,
                    icon: "bi-exclamation-octagon-fill",
                    kind: "danger"
                });
                if (qtyInput) qtyInput.classList.add("is-invalid");
                isError = true;
            } else if (qtyInput) {
                qtyInput.classList.remove("is-invalid");
            }
        }

        // (3) Duplicados de producto + lote contra otras filas erróneas.
        if (productId && lot) {
            document.querySelectorAll(".err-row-grid").forEach(other => {
                if (other === rowDiv) return;
                const oSel = other.querySelector(".err-product-select");
                const oLot = other.querySelector(".err-lot-input");
                if (oSel && oLot && oSel.value === productId
                    && oLot.value.trim().toLowerCase() === lot) {
                    messages.push({
                        text: `"${oSel.options[oSel.selectedIndex].text}" con lote "${lot}" ya está declarado en otra fila.`,
                        icon: "bi-files",
                        kind: "warning"
                    });
                    isError = true;
                }
            });
        }

        // Cantidad inválida o no positiva cuando SÍ se eligió producto: un insumo
        // erróneo debe declarar una cantidad mayor a cero. Antes este bloque era
        // inalcanzable (let/const + cortocircuito), así que la fila solo se
        // bloqueaba al enviar; ahora también marca la carpeta roja en vivo.
        if (!isError && productId && qtyInput &&
            (!Number.isFinite(qty) || qty <= 0)) {
            qtyInput.classList.add("is-invalid");
            isError = true;
            messages.push({
                text: "La cantidad debe ser un número mayor a cero.",
                icon: "bi-exclamation-circle-fill",
                kind: "warning"
            });
        }

        if (isError) {
            renderValidationHints(hint, messages);
            hint.classList.remove("d-none");
        } else {
            hint.innerHTML = "";
            hint.classList.add("d-none");
            // Restaurar el badge de estado del lote que oculta renderValidationHints
            // mientras hay errores, para volver a la vista normal.
            const lotBadge = rowDiv.querySelector(".err-exp-hint");
            if (lotBadge) lotBadge.classList.remove("d-none");
        }
        return !isError;
    }

    // Pinta cada mensaje de validación del insumo erróneo como una tarjeta de alerta
    // compacta y tipada (danger/warning) con su icono. Mucho más legible que un
    // párrafo de texto plano concatenado.
    function renderValidationHints(container, items) {
        container.innerHTML = items.map(m => `
            <div class="err-alert err-alert-${m.kind || "danger"}">
                <i class="bi ${m.icon || "bi-exclamation-circle-fill"} err-alert-icon"></i>
                <span>${m.text}</span>
            </div>
        `).join("");
        // Mientras haya un error de validación, oculto el badge de estado del lote
        // (".err-exp-hint": "lote detectado / no está en el sistema") para que las
        // tarjetas de advertencia no se vean encima ni junto a él. Si el lote se
        // corrige, el row vuelve a mostrarlo en el flujo normal.
        const row = container.closest(".err-row-grid");
        const lotBadge = row && row.querySelector(".err-exp-hint");
        if (lotBadge) lotBadge.classList.add("d-none");
    }

    // venir de varios lotes; el operario agrega un renglón por lote real del sobrante.
    // Al escribir el LOTE, el sistema lo reconoce y AUTOMÁTICAMENTE toma la fecha de
    // vencimiento (igual que el insumo erróneo). El operario no define el vencimiento:
    // lo saca el sistema del lote ya registrado.
    function addSurplusLotRow(row, index) {
        const list = row.querySelector(".surplus-lot-list");
        if (!list) return;
        const lotRow = document.createElement("div");
        lotRow.className = "surplus-lot-row w-100";
        lotRow.innerHTML = `
            <div class="surplus-lot-head">
                <span class="surplus-lot-num" data-surplus-index=""></span>
                <button type="button" class="btn btn-outline-danger btn-sm btn-remove-surplus-lot" title="Quitar lote">
                    <i class="bi bi-trash3"></i>
                </button>
            </div>
            <label class="surplus-field">
                <span>Lote</span>
                <input type="text" class="form-control form-control-sm input-surplus-lot font-monospace"
                       placeholder="Lote real del sobrante...">
            </label>
            <div class="surplus-field-row">
                <label class="surplus-field">
                    <span>Vencimiento (lo pone el sistema)</span>
                    <input type="date" class="form-control form-control-sm input-surplus-exp font-monospace" readonly>
                </label>
                <label class="surplus-field">
                    <span>Cantidad</span>
                    <input type="number" step="0.01" min="0" class="form-control form-control-sm input-surplus-qty font-monospace"
                           placeholder="0.00" aria-label="Cantidad del lote">
                </label>
            </div>
            <div class="surplus-lot-hint mt-1"></div>
        `;
        const numEl = lotRow.querySelector(".surplus-lot-num");
        numEl.textContent = `Lote del sobrante ${(index || 0) + 1}`;
        const btnRemove = lotRow.querySelector(".btn-remove-surplus-lot");
        btnRemove.addEventListener("click", () => {
            lotRow.remove();
            renumberSurplusRows(row);
        });
        const lotInput = lotRow.querySelector(".input-surplus-lot");
        // Debounce: al escribir el lote no se lanza una consulta por cada tecla,
        // solo tras 300 ms de pausa (igual que el insumo erróneo).
        let surplusLotDebounce = null;
        lotInput.addEventListener("input", () => {
            hideAlert();
            clearTimeout(surplusLotDebounce);
            surplusLotDebounce = setTimeout(() => handleSurplusLotLookup(lotRow, row), 300);
        });
        // Al cambiar la cantidad de un lote se refresca el resumen en vivo (cuánto va
        // y cuánto falta por repartir del sobrante total).
        const qtyInputRow = lotRow.querySelector(".input-surplus-qty");
        if (qtyInputRow) {
            qtyInputRow.addEventListener("input", () => updateSurplusSummary(row));
        }
        list.appendChild(lotRow);
        renumberSurplusRows(row);
    }

    // Renumera las filas de lote del sobrante ("Lote 1", "Lote 2"...).
    function renumberSurplusRows(row) {
        const list = row.querySelector(".surplus-lot-list");
        if (!list) return;
        list.querySelectorAll(".surplus-lot-row").forEach((lr, i) => {
            const num = lr.querySelector(".surplus-lot-num");
            if (num) num.textContent = `Lote del sobrante ${i + 1}`;
        });
        updateSurplusSummary(row);
    }

    // Resumen en vivo del PANEL "Lote(s) del sobrante": muestra cuál es el excedente
    // total que hay que repartir entre los lotes y cuánto falta por asignar, para que
    // el operario entienda exactamente qué cantidad debe escribir en cada lote.
    // La regla es: la SUMA de las cantidades de los lotes debe cuadrar EXACTAMENTE
    // con el sobrante total (recibido - despachado). Esto evita la confusión de
    // "escribo 60 pero pone cualquier número y me marca error".
    function updateSurplusSummary(row) {
        const summaryEl = row.querySelector(".surplus-summary");
        if (!summaryEl) return;

        const unit = row.dataset.unit || "UN";
        const input = row.querySelector(".input-received");
        const dispatched = parseFloat(row.dataset.dispatched) || 0;
        let received = parseFloat(input && input.value);
        if (isNaN(received) || received < 0) received = 0;

        const target = received - dispatched;
        const surplusBox = row.querySelector(".surplus-lots");
        if (!(target > 0.001) || (surplusBox && surplusBox.classList.contains("hidden"))) {
            summaryEl.innerHTML = "";
            return;
        }

        let sum = 0;
        row.querySelectorAll(".input-surplus-qty").forEach(q => {
            const v = parseFloat(q.value);
            if (!isNaN(v) && v > 0) sum += v;
        });

        const remaining = target - sum;
        const pending = remaining > 0.01 ? remaining : 0;
        const over = remaining < -0.01 ? -remaining : 0;

        const ok = Math.abs(remaining) <= 0.01;
        const statusClass = ok ? "surplus-sum-ok" : (sum > 0 ? "surplus-sum-wait" : "surplus-sum-empty");
        const statusIcon = ok ? "bi-check-circle-fill" : (sum > 0 ? "bi-hourglass-split" : "bi-pencil-fill");

        summaryEl.className = `surplus-summary small ${statusClass}`;
        summaryEl.innerHTML = `
            <i class="bi ${statusIcon}"></i>
            <span>
                <strong>Sobrante total: ${target} ${unit}</strong>
                ${ok
                    ? `<span class="surplus-sum-msg"> — ¡Cuadra! Los lotes suman ${sum} ${unit}.</span>`
                    : over > 0
                        ? `<span class="surplus-sum-msg"> — Le sobra ${over} ${unit}: los lotes suman ${sum} ${unit}, más de lo declarado. Reduzca o ajuste una cantidad.</span>`
                        : `<span class="surplus-sum-msg"><br>Reparta esta cantidad entre el/los lote(s). Van ${sum} ${unit}; faltan <strong>${pending} ${unit}</strong>.</span>`}
            </span>`;
    }

    // Consulta compartida del lote EN EL SISTEMA (producto + lote). Devuelve
    // Promise de null (no consultable) o { exists, expiration_date }.
    // Unifica los tres casos (lote del renglón, lote del sobrante, lote del
    // insumo erróneo) para no duplicar el fetch y el manejo de errores.
    function fetchLotExpiration(productId, lot) {
        const pid = parseInt(productId);
        const l = String(lot || "").trim();
        if (!pid || !l) return Promise.resolve(null);
        const url = `/logistics/movements/reception/lot-expiration?product_id=${encodeURIComponent(pid)}&lot_number=${encodeURIComponent(l)}`;
        return fetch(url, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        })
            .then(res => res.json().catch(() => ({})))
            .then(data => (data && data.success) ? data : null)
            .catch(() => null);
    }

    // Reconocimiento del lote del sobrante EN EL SISTEMA: al escribir el lote, se
    // consulta el histórico (igual que el insumo erróneo) y se autocompleta el
    // vencimiento + un badge que indica si existe o no en el sistema.
    function handleSurplusLotLookup(lotRow, row) {
        const lotInput = lotRow.querySelector(".input-surplus-lot");
        const expInput = lotRow.querySelector(".input-surplus-exp");
        const hint = lotRow.querySelector(".surplus-lot-hint");
        const productId = parseInt(row.dataset.productId);
        const lot = lotInput.value.trim();

        if (!productId || !lot) {
            if (expInput) expInput.value = "";
            if (hint) hint.innerHTML = "";
            lotInput.dataset.verified = "";
            return;
        }

        fetchLotExpiration(productId, lot).then(data => {
            if (!data) {
                if (hint) hint.innerHTML = "";
                return;
            }
            if (data.exists === false) {
                if (expInput) expInput.value = "";
                lotInput.dataset.verified = "no";
                hint.innerHTML = `
                    <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle px-2 py-1">
                        <i class="bi bi-search me-1"></i> Este registro de lote no se encuentra en el sistema
                    </span>`;
                return;
            }
            lotInput.dataset.verified = "1";
            if (data.expiration_date) {
                if (expInput) expInput.value = data.expiration_date;
                hint.innerHTML = `
                    <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle px-2 py-1">
                        <i class="bi bi-check-circle me-1"></i> Lote y vencimiento detectados
                    </span>`;
            } else {
                if (expInput) expInput.value = "";
                hint.innerHTML = `
                    <span class="badge rounded-pill bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle px-2 py-1">
                        <i class="bi bi-check2 me-1"></i> Lote registrado, sin vencimiento conocido
                    </span>`;
            }
        });
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

        fetchLotExpiration(productId, lot).then(data => {
            if (!data) {
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
                        <div class="err-alert err-alert-warning">
                            <i class="bi bi-search err-alert-icon"></i>
                            <span>Este registro de lote no se encuentra en el sistema</span>
                        </div>`;
                }
                return;
            }
            if (data.expiration_date) {
                expInput.value = data.expiration_date;
                if (hint) {
                    hint.className = "err-exp-hint";
                    hint.innerHTML = `
                        <div class="err-alert err-alert-success">
                            <i class="bi bi-check-circle err-alert-icon"></i>
                            <span>Lote y vencimiento detectados</span>
                        </div>`;
                }
                expInput.dataset.verified = "1";
            } else {
                expInput.value = "";
                expInput.dataset.verified = "";
                if (hint) {
                    hint.className = "err-exp-hint";
                    hint.innerHTML = `
                        <div class="err-alert err-alert-info">
                            <i class="bi bi-check2 err-alert-icon"></i>
                            <span>Lote registrado, sin vencimiento conocido</span>
                        </div>`;
                }
            }
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

    // Cuenta SOLO las filas de insumo no solicitado que realmente se completaron
    // (producto elegido + cantidad > 0). Una fila vacía agregada por error al tocar
    // "Registrar Insumo Entregado por Error" no debe forzar la sección abierta ni
    // interferir con una novedad como el Sobrante.
    function countMeaningfulErroneousRows() {
        if (!erroneousItemsList) return 0;
        let count = 0;
        erroneousItemsList.querySelectorAll(".err-row-grid").forEach(er => {
            const sel = er.querySelector(".err-product-select");
            const qtyInput = er.querySelector(".err-qty-input");
            const prodId = parseInt(sel ? sel.value : 0);
            const qty = qtyInput ? parseFloat(qtyInput.value) : NaN;
            if (prodId > 0 && qty > 0) count++;
        });
        return count;
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

        // La declaración de insumos no solicitados (erróneos) solo se muestra cuando
        // la novedad es "Producto Erróneo"/"Incidencia Mixta" O mientras existan filas
        // COMPLETADAS de insumos no solicitados. Los renglones vacíos (agregados por
        // error al tocar el botón) ya no mantienen la sección abierta: si el operario
        // pasa a declarar un Sobrante/Faltante, la sección se cierra y no persiste el
        // "agregar un insumo más" contradictorio.
        const hasMeaningfulErroneousRows = countMeaningfulErroneousRows() > 0;
        const showUnsolicited = novelty === "PRODUCTO_ERRONEO" || novelty === "INCIDENCIA_MIXTA" || hasMeaningfulErroneousRows;
        if (erroneousSection) {
            if (showUnsolicited) {
                erroneousSection.classList.remove("hidden");
                // Solo se auto-agrega una fila guía cuando NO hay NINGUNA fila aún
                // (ni siquiera vacía). Usar "sin filas completadas" aquí provocaba un
                // BUCLE INFINITO: addErroneousItemRow llama a checkAndAutoCategorize,
                // que llama a updateBadgeAndGuidance, que de nuevo agregaba una fila
                // vacía (nunca "completa") -> la página se colgaba. Con children.length
                // === 0 el ciclo se corta tras la primera fila.
                if (erroneousItemsList && erroneousItemsList.children.length === 0 && novelty === "PRODUCTO_ERRONEO") {
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

        fetchLotExpiration(productId, lot).then(data => {
            if (data) {
                updateLotExpiration(row, data.expiration_date || null, data.exists);
            } else {
                updateLotExpiration(row, null);
            }
        });
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
            const singleLotField = row.querySelector(".single-lot-field");
            const surplusLotsBox = row.querySelector(".surplus-lots");
            const surplusLotList = row.querySelector(".surplus-lot-list");

            let received = parseFloat(input.value);
            if (isNaN(received) || received < 0) received = 0;

            const diff = received - dispatched;

            // Auto-clasificación de la CONDICIÓN del renglón (feedback de pruebas):
            // si el operario NO tocó el selector de condición, al tipear una cantidad
            // distinta la fila se etiqueta sola como "Me faltó / Me sobró"; si la
            // cantidad vuelve a coincidir se restaura a Conforme. Si el operario
            // eligió la condición manualmente, se respeta su decisión.
            const conditionWasManual = condSelect ? row.dataset.condManual === "1" : true;
            if (condSelect) {
                if (!conditionWasManual) {
                    if (diff < -0.001) condSelect.value = "FALTANTE_CONTEO";
                    else if (diff > 0.001) condSelect.value = "SOBRANTE_EXCEDENTE";
                    else condSelect.value = "CONFORME";
                } else {
                    // Condiciones DE CANTIDAD elegidas a mano deben respaldarse con el
                    // conteo real. Si declaraste SOBRANTE pero recibiste igual o menos,
                    // (o FALTANTE pero recibiste igual o más), la cantidad contradice la
                    // condición: se corrige sola para no mostrar un "sobrante/faltante"
                    // inexistente en el formulario. Las condiciones de CALIDAD (lote,
                    // temperatura, custodia...) NO dependen de la cantidad y se respetan.
                    const manualCond = condSelect.value;
                    if (manualCond === "SOBRANTE_EXCEDENTE" && diff <= 0.001) {
                        condSelect.value = diff < -0.001 ? "FALTANTE_CONTEO" : "CONFORME";
                        row.dataset.condManual = "";
                    } else if (manualCond === "FALTANTE_CONTEO" && diff >= -0.001) {
                        condSelect.value = diff > 0.001 ? "SOBRANTE_EXCEDENTE" : "CONFORME";
                        row.dataset.condManual = "";
                    }
                }
            }

            const condition = condSelect ? condSelect.value : "CONFORME";

            const isSurplus = diff > 0.001;

            if (lotBox) {
                // El lote se pide tanto cuando el lote no coincide (LOTE_NO_COINCIDE)
                // como cuando hay un SOBRANTE: el excedente físico también debe indicar a
                // qué lote(es) pertenece. Sin esto el sobrante quedaría sin trazabilidad.
                const needsSingleLot = condition === "LOTE_NO_COINCIDE";
                if (needsSingleLot || isSurplus) {
                    lotBox.classList.remove("hidden");
                    // Lote no coincide: pide el lote físico real único del producto que
                    // se queda (obligatorio). Si además hay sobrante, se aclara que el
                    // excedente se registra por separado en el panel "Lote(s) del sobrante"
                    // (dos conceptos distintos: lo que se queda vs. el excedente a arbitraje).
                    if (needsSingleLot && singleLotField) {
                        singleLotField.classList.remove("hidden");
                        const lotRealInput = singleLotField.querySelector(".input-row-lot");
                        if (lotRealInput) {
                            lotRealInput.placeholder = isSurplus
                                ? "Lote físico real del insumo que se queda (el sobrante va más abajo)"
                                : "Lote físico real del insumo que se queda...";
                        }
                    }
                    else if (singleLotField) singleLotField.classList.add("hidden");
                    if (isSurplus) {
                        // Caso SOBRANTE (solo o combinado con lote no coincide): el
                        // excedente puede venir de 1..N lotes. Se muestra el panel
                        // "Lote(s) del sobrante" siempre que haya excedente físico,
                        // para que el backend nunca bloquee con un error que la UI no
                        // puede resolver. Mientras no haya lote declarado el panel se
                        // mantiene abierto (auto); luego respeta el colapso manual.
                        if (surplusLotsBox) surplusLotsBox.classList.remove("hidden");
                        if (surplusLotList && surplusLotList.children.length === 0) {
                            const sb = row.querySelector(".surplus-lot-body");
                            if (sb) sb.classList.remove("hidden");
                            const caret = row.querySelector(".surplus-caret");
                            if (caret) caret.classList.add("open");
                            addSurplusLotRow(row);
                        }
                    } else if (surplusLotsBox) {
                        surplusLotsBox.classList.add("hidden");
                    }
                } else {
                    lotBox.classList.add("hidden");
                    if (lotExpBox) lotExpBox.classList.add("hidden");
                }
            }

            // Refrescar el resumen en vivo del panel "Lote(s) del sobrante" cuando
            // cambia la cantidad recibida (y por tanto el excedente total a repartir).
            updateSurplusSummary(row);

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
                // Al marcar una condición específica en un renglón (p. ej. LOTE_NO_COINCIDE),
                // la clasificación general se sincroniza con esa condición en lugar de
                // quedarse clavada en una elección previa.
                userManuallyChangedNovelty = false;

                // Aviso claro cuando una condición DE CANTIDAD no está respaldada por el
                // conteo real. En lugar de solo re-categorizar en silencio, se le dice al
                // operario qué cantidad debe poner. callcheckAndAutoCategorize lo corrige.
                const chosen = condSelect.value;
                const dispatched = parseFloat(row.dataset.dispatched) || 0;
                const rcv = parseFloat(input.value);
                const diff = (isNaN(rcv) ? 0 : rcv) - dispatched;

                if (chosen === "SOBRANTE_EXCEDENTE" && diff <= 0.001) {
                    showAlert(
                        diff < -0.001
                            ? "Indicó 'Sobrante', pero la cantidad recibida es MENOR a la despachada. Un sobrante exige recibir más de lo despachado."
                            : "Indicó 'Sobrante', pero la cantidad recibida es IGUAL a la despachada. Para declarar un sobrante debe escribir una cantidad MAYOR a la despachada."
                    );
                } else if (chosen === "FALTANTE_CONTEO" && diff >= -0.001) {
                    showAlert(
                        diff > 0.001
                            ? "Indicó 'Faltante', pero la cantidad recibida es MAYOR a la despachada. Un faltante exige recibir menos de lo despachado."
                            : "Indicó 'Faltante', pero la cantidad recibida es IGUAL a la despachada. Para declarar un faltante debe escribir una cantidad MENOR a la despachada."
                    );
                }

                checkAndAutoCategorize();
            });
        }

        const lotInput = row.querySelector(".input-row-lot");
        if (lotInput) {
            // Debounce: al escribir el lote (insumo o excedente del sobrante) no se
            // lanza un fetch por cada tecla, solo tras 300 ms de pausa. Evita saturar
            // el servidor y la lentitud al teclear.
            let rowLotDebounce = null;
            lotInput.addEventListener("input", () => {
                hideAlert();
                clearTimeout(rowLotDebounce);
                rowLotDebounce = setTimeout(() => handleLotLookup(row), 300);
            });
        }

        const btnAddSurplus = row.querySelector(".btn-add-surplus-lot");
        if (btnAddSurplus) {
            btnAddSurplus.addEventListener("click", () => addSurplusLotRow(row));
        }

        // Toggle del panel "Lote(s) del sobrante": colapsa/expande el cuerpo. El
        // panel existe para que el usuario sepa que el sobrante exige declarar su
        // lote; al marcarlo como sobrante se abre solo (ver checkAndAutoCategorize).
        const btnToggleSurplus = row.querySelector(".btn-toggle-surplus-lots");
        const surplusBody = row.querySelector(".surplus-lot-body");
        const surplusCaret = row.querySelector(".surplus-caret");
        if (btnToggleSurplus && surplusBody) {
            btnToggleSurplus.addEventListener("click", () => {
                const willOpen = surplusBody.classList.contains("hidden");
                surplusBody.classList.toggle("hidden", !willOpen);
                if (surplusCaret) surplusCaret.classList.toggle("open", willOpen);
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
            const detailId = parseInt(row.dataset.detailId, 10);
            if (!Number.isFinite(detailId)) return;
            const dispatched = parseFloat(row.dataset.dispatched) || 0;
            const input = row.querySelector(".input-received");
            const condSelect = row.querySelector(".select-item-condition");
            const lotInput = row.querySelector(".input-row-lot");
            const expInput = row.querySelector(".input-row-exp");

            let receivedQty = parseFloat(input.value);
            if (isNaN(receivedQty) || receivedQty < 0) receivedQty = 0;

            const condition = condSelect ? condSelect.value : "CONFORME";
            // Mismo umbral de tolerancia que checkAndAutoCategorize (0.001): una
            // diferencia minúscula dentro del ruido no debe tratarse como sobrante,
            // para que la UI (que muestra el panel de lotes) y este payload coincidan.
            const isSurplus = (receivedQty - dispatched) > 0.001;
            // El lote del SOBRANTE se captura para trazabilidad (va a la auditoría y al
            // arbitraje), pero NO bloquea el envío: el sobrante legítimo sin lote debe
            // poder ir a disputa. Solo LOTE_NO_COINCIDE exige lote de forma bloqueante.
            const observedLot = (lotInput && condition === "LOTE_NO_COINCIDE")
                ? lotInput.value.trim()
                : null;

            if (condition === "LOTE_NO_COINCIDE" && !observedLot) {
                missingLotField = true;
            }

            // El excedente puede venir de 1..N lotes: se captura cada fila (lote +
            // cantidad + vencimiento) que el operario agregó en la lista de lotes del
            // sobrante. Cada lote se reconoce en el sistema (consulta lot-expiration).
            const surplusLots = [];
            let surplusSumQty = 0;
            let hasLotWithOutQty = false;
            let hasQtyWithoutLot = false;
            let surplusHasAnyLot = false;
            let surplusHasUnrecognizedLot = false;
            row.querySelectorAll(".surplus-lot-row").forEach(sr => {
                const sLot = sr.querySelector(".input-surplus-lot");
                const sExp = sr.querySelector(".input-surplus-exp");
                const sQty = sr.querySelector(".input-surplus-qty");
                const lotVal = sLot ? sLot.value.trim() : "";
                const lotVerified = sLot ? sLot.dataset.verified : "";
                const qtyVal = sQty ? parseFloat(sQty.value) : NaN;
                const qty = (isNaN(qtyVal) || qtyVal < 0) ? 0 : qtyVal;
                if (!lotVal && qty > 0) {
                    // Cantidad declarada sin lote: el backend solo suma lotes con nombre
                    // (named_lots), así que esta cantidad NO puede cuadrar el excedente.
                    // Se marca para obligar a escribir el lote (o vaciar la cantidad) y
                    // evitar que se pierda en silencio con una suma aparente correcta.
                    hasQtyWithoutLot = true;
                }
                if (lotVal || qty > 0) {
                    if (lotVal) {
                        surplusHasAnyLot = true;
                        // Solo un lote CONFIRMADO como inexistente debe bloquear. Si la
                        // consulta aún no respondió (verified vacío), NO se marca: el
                        // backend valida lot_exists como red de seguridad, evitando el
                        // falso bloqueo cuando el operario confirma justo al teclear.
                        if (lotVerified === "no") surplusHasUnrecognizedLot = true;
                        // Suma SOLO los lotes con nombre, igual que el backend (el
                        // excedente debe trazarse a lotes reconocidos del sistema).
                        if (qty === 0) hasLotWithOutQty = true;
                        else surplusSumQty += qty;
                    }
                    surplusLots.push({
                        lot: lotVal,
                        expiration_date: (lotVal && sExp && sExp.value) ? sExp.value : null,
                        quantity: qty
                    });
                }
            });

            // Techo de sobrante: el excedente no debería superar el stock físico del
            // producto en el ORIGEN (el sistema no lleva stock por lote, así que el
            // límite razonable es el stock del producto). Solo es ADVERTENCIA.
            const originStock = parseFloat(row.dataset.originStock) || 0;
            const extraUnits = isSurplus ? (receivedQty - dispatched) : 0;
            const exceedsOriginStock = extraUnits > originStock + 0.001;

            // Regla: un SOBRANTE es obligatorio declarar a qué lote(s) del sistema
            // pertenece el excedente. Sin al menos un lote escrito, se bloquea el
            // envío (igual que LOTE_NO_COINCIDE exige lote).
            const missingSurplusLot = isSurplus && !surplusHasAnyLot;

            // El lote del sobrante debe EXISTIR en el sistema (no es un dato libre).
            // Solo se bloquea cuando el sistema lo confirmó como inexistente (la
            // existencia se verifica de nuevo en el backend al procesar).
            const unrecognizedSurplusLot = isSurplus && surplusHasUnrecognizedLot;

            // Coherencia de cantidades: la suma de las cantidades de los lotes del
            // sobrante debe cuadrar con el excedente total recibido. Tanto un lote
            // sin cantidad como una cantidad sin lote se marcan para pedir que se
            // complete/corrija; el backend descarta las cantidades sin lote, así que
            // ambas señales evitan una suma aparente correcta que luego no cuadre.
            const surplusQtyMismatch = isSurplus && surplusHasAnyLot &&
                (hasLotWithOutQty || hasQtyWithoutLot || Math.abs(surplusSumQty - extraUnits) > 0.01);

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
                    : null,
                surplus_lots: surplusLots,
                extra_units: extraUnits,
                origin_stock: originStock,
                exceeds_origin_stock: exceedsOriginStock,
                missing_surplus_lot: missingSurplusLot,
                unrecognized_surplus_lot: unrecognizedSurplusLot,
                surplus_qty_mismatch: surplusQtyMismatch
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

        const missingSurplusLot = items.some(it => it.missing_surplus_lot);
        const unrecognizedSurplusLot = items.some(it => it.unrecognized_surplus_lot);
        const surplusQtyMismatch = items.some(it => it.surplus_qty_mismatch);

        return { items, erroneous, missingLotField, errInvalid, missingSurplusLot, unrecognizedSurplusLot, surplusQtyMismatch };
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        hideAlert();

        try {
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

        const { items, erroneous, missingLotField, errInvalid, missingSurplusLot, unrecognizedSurplusLot, surplusQtyMismatch } = buildReceptionPayload();
        const itemsPayload = items;
        const erroneousPayload = erroneous;

        if (missingLotField) {
            showAlert("Debe ingresar el lote físico real impreso en el empaque para el insumo marcado con Lote no coincide.");
            return;
        }

        if (missingSurplusLot) {
            showAlert("Debe declarar de qué lote del sistema proviene el sobrante. Escriba el lote en la fila de lote del sobrante para poder continuar.");
            return;
        }

        if (unrecognizedSurplusLot) {
            showAlert("El lote del sobrante debe estar registrado en el sistema. Escriba un lote existente (el sistema reconoce el lote y su vencimiento) antes de continuar.");
            return;
        }

        if (surplusQtyMismatch) {
            showAlert("La suma de las cantidades de los lotes del sobrante no coincide con el excedente total. Complete la cantidad de cada lote de modo que sumen exactamente el sobrante recibido.");
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

        // Bloquea filas erróneas con problemas detectados al momento de enviar:
        // producto que ya viene en la guía, cantidad que supera el stock del origen
        // (tope) o duplicados de producto+lote. La carpeta roja ya se muestra en vivo.
        if (erroneousPayload.length > 0) {
            let erroneousBlocked = false;
            document.querySelectorAll(".err-row-grid").forEach(vr => {
                if (!validateErroneousRow(vr)) erroneousBlocked = true;
            });
            if (erroneousBlocked) {
                showAlert("Corrija la fila de insumo erróneo marcada en rojo (producto ya en la guía, cantidad que supera el stock del origen o lote duplicado).");
                return;
            }
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

            // Desglose por lote del sobrante (el excedente puede venir de varios lotes).
            // Solo se listan las entradas que tienen lote; una sin lote no debe
            // imprimirse como "(sin lote)" (los guards ya bloquean ese caso antes).
            let surplusLotsHtml = "";
            const namedSurplusLots = (it.surplus_lots || []).filter(sl => sl.lot);
            if (namedSurplusLots.length > 0) {
                const lotsDetail = namedSurplusLots
                    .map(sl => {
                        const qtyText = (sl.quantity > 0) ? ` — ${sl.quantity.toFixed(2)} ${it.unit}` : " — (sin cantidad)";
                        const expText = (sl.expiration_date) ? ` · vence ${sl.expiration_date}` : "";
                        return `<span class="text-muted small d-block">· Lote ${sl.lot}${expText}${qtyText}</span>`;
                    })
                    .join("");
                surplusLotsHtml = `<div class="mt-1">${lotsDetail}</div>`;
            }

            // Aviso (NO bloqueo) cuando el sobrante supera el stock físico del origen.
            let surplusWarnHtml = "";
            if (it.exceeds_origin_stock) {
                surplusWarnHtml = `
                    <div class="mt-1 text-danger small fw-bold" role="alert">
                        <i class="bi bi-exclamation-triangle-fill"></i>
                        El sobrante (+${it.extra_units.toFixed(2)} ${it.unit}) supera el stock disponible del producto en el origen
                        (${it.origin_stock || 0} ${it.unit} de ese producto, sin desglose por lote). Verifique que el excedente físico realmente exista.
                    </div>`;
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
                    ${surplusWarnHtml}
                    ${surplusLotsHtml}
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
        // Se deshabilita el botón de envío mientras el modal está abierto, para
        // evitar el doble envío si el operario vuelve a hacer clic en "Confirmar"
        // (dos modales / dos POST concurrentes). Se rehabilita al cancelar.
        btnSubmit.disabled = true;
        } catch (err) {
            console.error("Error al procesar la recepción:", err);
            showAlert("Ocurrió un error inesperado al confirmar. Revise los datos e intente de nuevo.");
            btnSubmit.disabled = false;
            updateBadgeAndGuidance();
        }
    });

    btnCancelModal.addEventListener("click", () => {
        confirmModal.classList.add("hidden");
        btnSubmit.disabled = false;
        updateBadgeAndGuidance();
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

        // Aviso de techo (NO bloqueo): si algún sobrante supera el stock físico del
        // producto en el origen, se pide una confirmación explícita del operario antes
        // de asentar. El excedente igual queda para arbitraje (no se acredita de más),
        // pero evita confirmar "a ciegas" un excedente que físicamente no cabe.
        const exceedsOrigin = (payload.items || []).filter(it => it.exceeds_origin_stock);
        if (exceedsOrigin.length > 0) {
            const names = exceedsOrigin.map(it => it.product_name).join(", ");
            const okToProceed = window.confirm(
                `Atención: el sobrante de ${names} supera el stock disponible del producto en el origen. ` +
                "(El inventario se mide por producto, sin desglose por lote.) " +
                "Verifique que el excedente físico realmente exista antes de confirmar. ¿Desea continuar?"
            );
            if (!okToProceed) {
                confirmModal.classList.remove("hidden");
                btnSubmit.disabled = false;
                updateBadgeAndGuidance();
                return;
            }
        }

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