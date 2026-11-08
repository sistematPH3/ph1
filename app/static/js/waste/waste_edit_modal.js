/* =========================================================
   MODAL DE EDICIÓN DE MERMA PENDIENTE
   ---------------------------------------------------------
   Se abre desde "Mis Mermas Pendientes" (merma_list.html).
   - Carga los datos de la merma con GET /api/waste/merma/<id>/edit
   - Permite cambiar tipo, motivo, evidencia general, y ajustar
     las líneas PENDIENTES (producto + lote + cantidad + fotos).
   - Las líneas que YA tomaron decisión (aprobadas/rechazadas por
     el admin en una resolución parcial) se muestran SOLO lectura:
     no se pueden editar ni quitar.
   - Cuando el tipo seleccionado es VENCIDO, SOLO se listan los
     productos y lotes vencidos de la sede (nunca los buenos).
   - Las fotos se suben a ImgBB por el endpoint /api/waste/evidence.
   - Guarda con POST /api/waste/merma/<id>/edit.
   ========================================================= */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const modalEl = document.getElementById("editMermaModal");
        if (!modalEl) return;

        const pageAlertBox = document.getElementById("cancelAlerts");
        const editModal = bootstrap.Modal.getOrCreateInstance(modalEl);
        const body = document.getElementById("editMermaLinesBody");
        const notesInput = document.getElementById("editWasteNotes");
        const vencidoBanner = document.getElementById("editVencidoBanner");
        const alertsBox = document.getElementById("editMermaAlerts");
        const btnSave = document.getElementById("btnSaveEditMerma");
        const confirmMermaModalEl = document.getElementById("confirmEditMermaModal");
        const confirmMermaSummary = document.getElementById("confirmEditMermaSummary");
        const confirmMermaWasteIdEl = document.getElementById("confirmEditMermaWasteId");
        const btnConfirmMermaSave = document.getElementById("btnConfirmSaveEditMerma");
        const totalBox = document.getElementById("editWasteTotal");

        const headerPhotoImg = document.getElementById("editHeaderPhoto");
        const headerPhotoPlaceholder = document.getElementById("editHeaderPhotoPlaceholder");
        const headerPhotoInput = document.getElementById("editHeaderPhotoInput");
        const btnHeaderPhotoAdd = document.getElementById("btnEditHeaderPhotoAdd");
        const btnHeaderPhotoRemove = document.getElementById("btnEditHeaderPhotoRemove");

        let current = null;
        let productsCache = [];
        let vencidosByProduct = {};
        let lotsCache = {};
        let headerPhotoUrl = null;
        let headerUploadSeq = 0;
        let pendingSave = null;

        function esc(str) {
            return String(str == null ? "" : str).replace(/[&<>"']/g, function (m) {
                return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
            });
        }

        function showPageAlert(message, isError) {
            if (!pageAlertBox) return;
            pageAlertBox.innerHTML = "";
            const div = document.createElement("div");
            div.className = "alert " + (isError ? "alert-danger" : "alert-success") +
                " d-flex align-items-center border-0";
            div.innerHTML = (isError
                    ? '<i class="bi bi-exclamation-triangle-fill me-2"></i>'
                    : '<i class="bi bi-check-circle-fill me-2"></i>') + esc(message);
            pageAlertBox.appendChild(div);
            window.scrollTo({ top: 0, behavior: "smooth" });
        }

        function showModalAlert(message, isError) {
            if (!alertsBox) return;
            alertsBox.innerHTML = "";
            const div = document.createElement("div");
            div.className = "alert " + (isError ? "alert-danger" : "alert-warning") + " py-2 small border-0";
            div.innerHTML = (isError
                    ? '<i class="bi bi-exclamation-triangle-fill me-2"></i>'
                    : '<i class="bi bi-info-circle-fill me-2"></i>') + esc(message);
            alertsBox.appendChild(div);
        }

        function fetchJSON(url) {
            return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } }).then(function (res) {
                return res.json();
            });
        }

        function anyLineVencidoSelect() {
            let any = false;
            body.querySelectorAll(".edit-tipo-select").forEach(function (s) {
                if (!any) {
                    const opt = s.options[s.selectedIndex];
                    if (opt && opt.dataset.code === "VENCIDO") any = true;
                }
            });
            return any;
        }

        function updateVencidoBanner() {
            if (!vencidoBanner) return;
            vencidoBanner.classList.toggle("d-none", !anyLineVencidoSelect());
        }

        function productsDisponibles() {
            return productsCache;
        }

        async function loadVencidos(locationId) {
            vencidosByProduct = {};
            try {
                const data = await fetchJSON("/api/waste/locations/" + locationId + "/vencidos");
                if (data.success) {
                    (data.vencidos || []).forEach(function (v) {
                        if (!vencidosByProduct[v.product_id]) vencidosByProduct[v.product_id] = [];
                        vencidosByProduct[v.product_id].push({
                            lot_number: v.lot_number,
                            quantity: v.quantity,
                            expiration_date: v.expiration_date
                        });
                    });
                }
            } catch (e) {
                vencidosByProduct = {};
            }
        }

        function uploadToEvidence(file) {
            return new Promise(function (resolve) {
                const formData = new FormData();
                formData.append("image", file);
                fetch("/api/waste/evidence", { method: "POST", body: formData })
                    .then(function (res) { return res.json(); })
                    .then(function (result) {
                        if (result && result.success && result.url) {
                            resolve(result.url);
                        } else {
                            showModalAlert("Una foto no se pudo cargar; puede continuar sin ella.", true);
                            resolve(null);
                        }
                    })
                    .catch(function () {
                        showModalAlert("Error de conexión al subir una foto; puede continuar sin ella.", true);
                        resolve(null);
                    });
            });
        }

        /* --------------------------------------------------
           Evidencia general (foto del ticket)
           -------------------------------------------------- */
        function syncHeaderPhotoUI() {
            if (headerPhotoUrl) {
                headerPhotoImg.src = headerPhotoUrl;
                headerPhotoImg.classList.remove("d-none");
                headerPhotoPlaceholder.classList.add("d-none");
                btnHeaderPhotoAdd.classList.add("d-none");
                btnHeaderPhotoRemove.classList.remove("d-none");
            } else {
                headerPhotoImg.removeAttribute("src");
                headerPhotoImg.classList.add("d-none");
                headerPhotoPlaceholder.classList.remove("d-none");
                btnHeaderPhotoAdd.classList.remove("d-none");
                btnHeaderPhotoRemove.classList.add("d-none");
            }
        }

        function bindHeaderPhotoEvents() {
            if (!btnHeaderPhotoAdd) return;
            headerPhotoImg.addEventListener("click", function () {
                if (headerPhotoUrl) window.open(headerPhotoUrl, "_blank");
            });
            btnHeaderPhotoAdd.addEventListener("click", function () {
                if (headerPhotoInput) headerPhotoInput.click();
            });
            btnHeaderPhotoRemove.addEventListener("click", function () {
                headerPhotoUrl = null;
                if (headerPhotoInput) headerPhotoInput.value = "";
                syncHeaderPhotoUI();
            });
            if (headerPhotoInput) {
                headerPhotoInput.addEventListener("change", function () {
                    const file = headerPhotoInput.files && headerPhotoInput.files[0];
                    if (!file) return;
                    if (!file.type || !file.type.startsWith("image/")) {
                        showModalAlert("Solo se permiten archivos de imagen.", true);
                        return;
                    }
                    const seq = ++headerUploadSeq;
                    btnHeaderPhotoAdd.disabled = true;
                    uploadToEvidence(file).then(function (url) {
                        btnHeaderPhotoAdd.disabled = false;
                        if (url && seq === headerUploadSeq) {
                            headerPhotoUrl = url;
                            syncHeaderPhotoUI();
                        }
                    });
                });
            }
        }

        /* --------------------------------------------------
           Fotos por línea (producto)
           -------------------------------------------------- */
        function renderLinePhotos(cell, photosArr, readOnly) {
            cell.innerHTML = "";
            const wrap = document.createElement("div");
            wrap.className = "d-flex align-items-center flex-wrap gap-1";

            (photosArr || []).forEach(function (url) {
                const box = document.createElement("div");
                box.style.cssText = "position:relative;";
                const img = document.createElement("img");
                img.src = url;
                img.style.cssText = "width:56px;height:56px;object-fit:cover;border-radius:8px;cursor:pointer;";
                img.title = "Ver foto";
                img.addEventListener("click", function () { window.open(url, "_blank"); });
                box.appendChild(img);
                if (!readOnly) {
                    const del = document.createElement("button");
                    del.type = "button";
                    del.title = "Quitar esta foto";
                    del.className = "btn btn-xs btn-outline-danger rounded-circle p-0";
                    del.style.cssText = "position:absolute;top:-6px;right:-6px;width:18px;height:18px;";
                    del.innerHTML = '<i class="bi bi-x" style="font-size:12px;"></i>';
                    del.addEventListener("click", function () {
                        const i = photosArr.indexOf(url);
                        if (i !== -1) photosArr.splice(i, 1);
                        renderLinePhotos(cell, photosArr, false);
                    });
                    box.appendChild(del);
                }
                wrap.appendChild(box);
            });

            if (!readOnly) {
                const addBtn = document.createElement("button");
                addBtn.type = "button";
                addBtn.title = "Subir foto";
                addBtn.className = "btn btn-sm btn-outline-primary rounded-circle";
                addBtn.style.cssText = "width:56px;height:56px;";
                addBtn.innerHTML = '<i class="bi bi-plus-lg"></i>';
                const fileInput = document.createElement("input");
                fileInput.type = "file";
                fileInput.accept = "image/*";
                fileInput.className = "d-none";
                fileInput.addEventListener("change", function () {
                    const file = fileInput.files && fileInput.files[0];
                    if (!file) return;
                    if (!file.type || !file.type.startsWith("image/")) {
                        showModalAlert("Solo se permiten archivos de imagen.", true);
                        return;
                    }
                    if ((photosArr || []).length >= 10) {
                        showModalAlert("Máximo 10 fotos por producto.", true);
                        return;
                    }
                    addBtn.disabled = true;
                    addBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
                    uploadToEvidence(file).then(function (url) {
                        addBtn.disabled = false;
                        addBtn.innerHTML = '<i class="bi bi-plus-lg"></i>';
                        if (url) {
                            photosArr.push(url);
                            renderLinePhotos(cell, photosArr, false);
                        }
                    });
                });
                addBtn.addEventListener("click", function () {
                    if ((photosArr || []).length < 10) fileInput.click();
                    else showModalAlert("Máximo 10 fotos por producto.", true);
                });
                wrap.appendChild(fileInput);
                wrap.appendChild(addBtn);
            }

            if (photosArr.length === 0 && readOnly) {
                wrap.appendChild(document.createTextNode("Sin fotos"));
                wrap.className += " text-muted small";
            }
            cell.appendChild(wrap);
        }

        /* --------------------------------------------------
           Fila de SOLO LECTURA (decisión ya tomada)
           -------------------------------------------------- */
        function renderDecidedRow(line) {
            const tr = document.createElement("tr");
            tr.dataset.decidedRow = "true";
            tr.dataset.qty = line.quantity;
            tr.className = line.status === "APROBADO" ? "bg-success-subtle" : "bg-danger-subtle";
            const badgeClass = line.status === "APROBADO" ? "text-bg-success" : "text-bg-danger";
            const badgeText = line.status === "APROBADO" ? "Aprobado" : "Rechazado";
            const reason = (line.resolution_reason || "").trim();

            tr.innerHTML =
                '<td class="py-1"><div class="fw-bold text-dark">' +
                '<i class="bi bi-lock-fill text-secondary me-1" title="Decisión tomada"></i>' +
                esc(line.product_name) + '</div>' +
                '<div class="text-muted small">' + esc(line.sku || "") + '</div></td>' +
                '<td class="py-1"><span class="badge bg-light text-dark border">' +
                esc(line.waste_type_name || "N/A") + '</span></td>' +
                '<td class="py-1"><span class="badge bg-light text-dark border">' + esc(line.lot_number) + '</span></td>' +
                '<td class="edit-exp text-muted small align-middle">' +
                (line.expiration_date ? esc(line.expiration_date) : "N/A") + "</td>" +
                '<td class="py-1"><span class="fw-bold">' + esc(line.quantity) + " " + esc(line.unit || "uds") +
                '</span></td>' +
                '<td class="py-1" data-photos-cell></td>' +
                '<td class="py-1 text-center align-middle text-nowrap"><span class="badge ' + badgeClass + '"' +
                (reason ? (' title="' + esc(reason) + '"') : "") + '>' +
                '<i class="bi bi-lock me-1"></i>Decisión tomada (' + badgeText + ')</span></td>';

            body.appendChild(tr);
            const photosCell = tr.querySelector("[data-photos-cell]");
            renderLinePhotos(photosCell, (line.photos || []).slice(), true);
        }

        /* --------------------------------------------------
           Fila EDITABLE (PENDIENTE)
           -------------------------------------------------- */
        function renderEditableRow(line) {
            line = line || {};
            const products = productsDisponibles();
            let pid = line.product_id;
            if (!(products.some(function (p) { return String(p.id) === String(pid); }))) {
                pid = products.length ? products[0].id : null;
            }

            const rowPhotos = (line.photos || []).slice();

            const lineTypeId = line.waste_type_id || current.waste_type_id;
            const tipoOptions = (current.waste_types || []).map(function (t) {
                return '<option value="' + t.id + '" data-code="' + esc(t.code || "") + '"' +
                    (String(t.id) === String(lineTypeId) ? " selected" : "") + ">" +
                    esc(t.name) + (t.severity ? " (G: " + esc(t.severity) + ")" : "") + "</option>";
            }).join("");

            const tr = document.createElement("tr");
            tr.innerHTML =
                '<td class="py-1"><select class="form-select form-select-sm edit-prod-select">' +
                products.map(function (p) {
                    return '<option value="' + p.id + '"' +
                        (String(p.id) === String(pid) ? " selected" : "") + ">" +
                        esc(p.name) + "</option>";
                }).join("") +
                "</select></td>" +
                '<td class="py-1"><select class="form-select form-select-sm edit-tipo-select">' +
                tipoOptions + "</select></td>" +
                '<td class="py-1"><select class="form-select form-select-sm edit-lot-select"></select></td>' +
                '<td class="edit-exp text-muted small align-middle">---</td>' +
                '<td class="py-1"><div class="input-group input-group-sm">' +
                '<input type="number" step="0.01" min="0.01" class="form-control text-center edit-qty" value="' +
                esc(line.quantity != null ? line.quantity : "0.01") + '" />' +
                '<span class="input-group-text edit-unit">' + esc(line.unit || "uds") + "</span>" +
                '</div><div class="form-text text-muted edit-stock-hint"></div></td>' +
                '<td class="py-1"><div class="edit-photos-cell"></div></td>' +
                '<td class="py-1 text-center align-middle"><button type="button" class="btn btn-sm btn-outline-secondary rounded-pill edit-remove-row" title="Quitar producto">' +
                '<i class="bi bi-x-lg"></i></button></td>';
            body.appendChild(tr);

            const prodSel = tr.querySelector(".edit-prod-select");
            const lotSel = tr.querySelector(".edit-lot-select");
            const qtyInput = tr.querySelector(".edit-qty");
            const expTd = tr.querySelector(".edit-exp");
            const hint = tr.querySelector(".edit-stock-hint");
            const unitText = esc(line.unit || "uds");
            const photosCell = tr.querySelector(".edit-photos-cell");
            renderLinePhotos(photosCell, rowPhotos, false);

            const lineLots = (line.available_lots || []).map(function (l) {
                return {
                    lot_number: l.lot_number,
                    expiration_date: l.expiration_date,
                    quantity: (l.stock != null ? l.stock : l.quantity)
                };
            });

            function lotOptionHtml(l) {
                const exp = l.expiration_date || "";
                const stock = (l.stock != null) ? l.stock : (l.quantity != null ? l.quantity : 0);
                return '<option value="' + esc(l.lot_number) + '" data-exp="' + esc(exp) +
                    '" data-stock="' + esc(stock) + '">' + esc(l.lot_number) + "</option>";
            }

            function lineEsVencido() {
                const tipoSel = tr.querySelector(".edit-tipo-select");
                const opt = tipoSel ? tipoSel.options[tipoSel.selectedIndex] : null;
                return !!opt && opt.dataset.code === "VENCIDO";
            }

            function filterByVencido(lots) {
                if (!lineEsVencido()) return lots;
                const pidx = parseInt(prodSel.value, 10);
                const venSet = new Set(
                    (vencidosByProduct[pidx] || []).map(function (v) { return v.lot_number; })
                );
                return lots.filter(function (l) { return venSet.has(l.lot_number); });
            }

            function renderLots(lots, keepLot) {
                lots = filterByVencido(lots);
                let html = lots.map(lotOptionHtml).join("");
                if (keepLot && !lots.some(function (l) { return String(l.lot_number) === String(keepLot); })) {
                    html = '<option value="' + esc(keepLot) + '" data-exp="' + esc(line.expiration_date || "") +
                        '" data-stock="0">' + esc(keepLot) + " (actual)</option>" + html;
                }
                lotSel.innerHTML = html;
                if (keepLot) lotSel.value = keepLot;
                update();
            }

            function fetchLots(pidx, keepLot) {
                if (lotsCache[pidx]) {
                    renderLots(lotsCache[pidx], keepLot);
                    return;
                }
                fetchJSON("/api/waste/locations/" + current.location_id + "/products/" + pidx + "/lots")
                    .then(function (data) {
                        if (data.success) {
                            lotsCache[pidx] = (data.lots || []).map(function (l) {
                                return {
                                    lot_number: l.lot_number,
                                    expiration_date: l.expiration_date,
                                    quantity: l.quantity
                                };
                            });
                        }
                        renderLots(lotsCache[pidx] || [], keepLot);
                    })
                    .catch(function () {
                        renderLots([], keepLot);
                    });
            }

            function clampQty() {
                let v = parseFloat(qtyInput.value);
                if (isNaN(v)) return;
                const maxStock = lotSel.options[lotSel.selectedIndex]
                    ? (parseFloat(lotSel.options[lotSel.selectedIndex].dataset.stock) || 0)
                    : 0;
                if (maxStock > 0 && v > maxStock) {
                    qtyInput.value = maxStock;
                    qtyInput.classList.add("is-invalid");
                    setTimeout(function () { qtyInput.classList.remove("is-invalid"); }, 800);
                } else if (v < 0) {
                    qtyInput.value = "0.01";
                }
                recalcTotal();
            }

            function update() {
                const opt = lotSel.options[lotSel.selectedIndex];
                if (opt) {
                    expTd.textContent = opt.dataset.exp ? opt.dataset.exp : "N/A";
                    hint.textContent = "M\u00e1ximo en lote: " + (parseFloat(opt.dataset.stock) || 0) + " " + unitText;
                } else {
                    expTd.textContent = "---";
                    hint.textContent = "Seleccione un lote.";
                }
            }

            prodSel.addEventListener("change", function () {
                lotSel.innerHTML = "";
                update();
                fetchLots(parseInt(prodSel.value, 10), "");
            });

            const tipoSel = tr.querySelector(".edit-tipo-select");
            tipoSel.addEventListener("change", function () {
                const keep = lotSel.value;
                lotSel.innerHTML = "";
                update();
                updateVencidoBanner();
                if (lineEsVencido() && Object.keys(vencidosByProduct).length === 0) {
                    loadVencidos(current.location_id)
                        .then(function () { fetchLots(parseInt(prodSel.value, 10), keep); })
                        .catch(function () { fetchLots(parseInt(prodSel.value, 10), keep); });
                } else {
                    fetchLots(parseInt(prodSel.value, 10), keep);
                }
            });

            lotSel.addEventListener("change", clampQty);
            lotSel.addEventListener("change", update);
            qtyInput.addEventListener("input", clampQty);
            qtyInput.addEventListener("blur", clampQty);

            const removeBtn = tr.querySelector(".edit-remove-row");
            removeBtn.addEventListener("click", function () {
                if (body.querySelectorAll("tr").length <= 1) {
                    showModalAlert("La merma debe conservar al menos un producto.", true);
                    return;
                }
                tr.remove();
                recalcTotal();
            });

            // Inicial: primera con los lotes de la línea (rápido), luego se
            // refresca con el endpoint para reflejar la disponibilidad real.
            if (pid != null) {
                renderLots(lineLots, line.lot_number || "");
                fetchLots(pid, line.lot_number || "");
            } else {
                renderLots([], "");
            }

            // Exponer las fotos de la fila para el guardado final.
            tr._linePhotos = rowPhotos;
        }

        function recalcTotal() {
            if (!totalBox) return;
            let total = 0;
            body.querySelectorAll("tr").forEach(function (tr) {
                const qty = tr.querySelector(".edit-qty");
                if (qty) {
                    const v = parseFloat(qty.value);
                    if (!isNaN(v) && v > 0) total += v;
                } else if (tr.dataset.decidedRow) {
                    const v = parseFloat(tr.dataset.qty);
                    if (!isNaN(v)) total += v;
                }
            });
            totalBox.textContent = total.toFixed(2);
        }

        function reRenderLines() {
            body.innerHTML = "";
            (current.lines || []).forEach(function (l) {
                if (l.decided) renderDecidedRow(l);
                else renderEditableRow(l);
            });
            syncSaveAvailability();
            recalcTotal();
        }

        function syncSaveAvailability() {
            btnSave.disabled = body.querySelectorAll(".edit-prod-select").length === 0;
        }

        async function openEdit(id) {
            current = null;
            productsCache = [];
            vencidosByProduct = {};
            lotsCache = {};
            headerPhotoUrl = null;
            if (alertsBox) alertsBox.innerHTML = "";
            vencidoBanner.classList.add("d-none");

            let data;
            try {
                data = await fetchJSON("/api/waste/merma/" + id + "/edit");
            } catch (e) {
                showPageAlert("No se pudo cargar la merma para editar.", true);
                return;
            }
            if (!data || !data.success) {
                showPageAlert((data && data.message) || "No se pudo cargar la merma para editar.", true);
                return;
            }

            current = data.waste;
            if (!current.can_edit) {
                showPageAlert("Esta merma ya no es editable o no tiene permisos sobre la sede.", true);
                return;
            }

            document.getElementById("editWasteIdTitle").textContent = current.id;
            document.getElementById("editWasteLocation").textContent = current.location_name;
            document.getElementById("editWasteDate").textContent = current.date || "---";
            document.getElementById("editWasteAuthor").textContent = current.author_name;
            notesInput.value = current.notes || "";

            headerPhotoUrl = current.evidence_url || null;
            if (headerPhotoInput) headerPhotoInput.value = "";
            syncHeaderPhotoUI();

            try {
                const pdata = await fetchJSON("/api/waste/locations/" + current.location_id + "/products");
                productsCache = (pdata.products || []);
            } catch (e) {
                productsCache = [];
            }

            const anyLineVencido = (current.lines || []).some(function (l) {
                return String(l.waste_type_code) === "VENCIDO";
            });
            if (current.is_vencido || anyLineVencido) {
                await loadVencidos(current.location_id);
            }

            reRenderLines();
            updateVencidoBanner();
            editModal.show();
        }

        // --- Botones "Editar" de la tabla ---
        document.querySelectorAll(".btn-edit-merma").forEach(function (btn) {
            btn.addEventListener("click", function () {
                openEdit(parseInt(this.dataset.id, 10));
            });
        });

        bindHeaderPhotoEvents();

        // --- Guardar ---
        btnSave.addEventListener("click", async function () {
            if (!current) return;

            const rows = body.querySelectorAll("tr");

            const lines = [];
            let hasError = false;

            rows.forEach(function (tr) {
                const prodSel = tr.querySelector(".edit-prod-select");
                const isEditable = !!prodSel;
                if (!isEditable) return;

                const tipoSel = tr.querySelector(".edit-tipo-select");
                const lotSel = tr.querySelector(".edit-lot-select");
                const qtyInput = tr.querySelector(".edit-qty");
                const pid = parseInt(prodSel.value, 10);
                const lot = (lotSel.value || "").trim();
                const qty = parseFloat(qtyInput.value);
                const lineTypeId = tipoSel ? parseInt(tipoSel.value, 10) : null;
                const maxStock = lotSel.options[lotSel.selectedIndex]
                    ? (parseFloat(lotSel.options[lotSel.selectedIndex].dataset.stock) || 0)
                    : 0;

                if (!lot) {
                    lotSel.classList.add("is-invalid");
                    hasError = true;
                } else {
                    lotSel.classList.remove("is-invalid");
                }

                if (isNaN(qty) || qty <= 0 || (maxStock > 0 && qty > maxStock)) {
                    qtyInput.classList.add("is-invalid");
                    hasError = true;
                } else {
                    qtyInput.classList.remove("is-invalid");
                }

                lines.push({
                    product_id: pid,
                    lot_number: lot,
                    quantity: qty,
                    waste_type_id: lineTypeId,
                    evidence_urls: tr._linePhotos || []
                });
            });

            if (hasError) {
                showModalAlert(
                    "Verifique las l\u00edneas: seleccione un lote para cada producto y una cantidad mayor a cero sin superar el m\u00e1ximo del lote.",
                    true
                );
                return;
            }

            if (lines.length === 0) {
                showModalAlert("No hay l\u00edneas pendientes por editar en esta merma.", true);
                return;
            }

            pendingSave = {
                notes: notesInput.value.trim(),
                evidence_url: headerPhotoUrl,
                lines: lines
            };

            renderConfirmMermaSummary(pendingSave);
            if (confirmMermaWasteIdEl) confirmMermaWasteIdEl.textContent = "#" + current.id;
            if (confirmMermaModalEl) {
                bootstrap.Modal.getOrCreateInstance(confirmMermaModalEl).show();
            }
        });

        function renderConfirmMermaSummary(payload) {
            if (!confirmMermaSummary) return;
            let html = '';

            if (payload.notes) {
                html += '<div class="mb-3">' +
                    '<span class="small fw-bold text-muted d-block">Motivo / Observaciones</span>' +
                    '<div class="p-2 rounded-3 bg-light border small">' + esc(payload.notes) + '</div></div>';
            }

            html += '<div class="table-responsive rounded-3 border">' +
                '<table class="table table-sm align-middle mb-0">' +
                '<thead class="text-uppercase small text-muted" style="background:#f8f9fa;">' +
                '<tr><th>Producto</th><th>Lote</th><th class="text-center">Cantidad</th><th>Motivo del insumo</th></tr>' +
                '</thead><tbody>';

            const editableRows = [];
            body.querySelectorAll("tr").forEach(function (tr) {
                if (tr.querySelector(".edit-prod-select")) editableRows.push(tr);
            });

            editableRows.forEach(function (tr, idx) {
                const line = payload.lines[idx];
                if (!line) return;
                const prodSel = tr.querySelector(".edit-prod-select");
                const prodName = (prodSel && prodSel.selectedIndex >= 0)
                    ? prodSel.options[prodSel.selectedIndex].text
                    : "Producto #" + line.product_id;
                const tipoSel = tr.querySelector(".edit-tipo-select");
                const tipoName = (tipoSel && tipoSel.selectedIndex >= 0)
                    ? tipoSel.options[tipoSel.selectedIndex].text
                    : "—";
                html += '<tr>' +
                    '<td class="fw-bold">' + esc(prodName) + '</td>' +
                    '<td>' + esc(line.lot_number) + '</td>' +
                    '<td class="text-center fw-bold">' + esc(line.quantity) + '</td>' +
                    '<td>' + esc(tipoName) + '</td></tr>';
            });

            html += '</tbody></table></div>';
            confirmMermaSummary.innerHTML = html;
        }

        if (btnConfirmMermaSave) {
            btnConfirmMermaSave.addEventListener("click", async function () {
                if (!pendingSave) return;
                btnConfirmMermaSave.disabled = true;
                btnConfirmMermaSave.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Guardando...';

                try {
                    const res = await fetch("/api/waste/merma/" + current.id + "/edit", {
                        method: "POST",
                        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                        body: JSON.stringify(pendingSave)
                    });
                    const data = await res.json();
                    if (confirmMermaModalEl && bootstrap.Modal.getInstance(confirmMermaModalEl)) {
                        bootstrap.Modal.getInstance(confirmMermaModalEl).hide();
                    }
                    if (res.ok && data.success) {
                        editModal.hide();
                        showPageAlert(data.message || "Merma actualizada correctamente.", false);
                        setTimeout(function () { window.location.reload(); }, 900);
                    } else {
                        const msg = data.message || (data.errors ? Object.values(data.errors)[0] : "No se pudo guardar la merma.");
                        showModalAlert(msg, true);
                    }
                } catch (err) {
                    showModalAlert("Error de comunicaci\u00f3n con el servidor al guardar la merma.", true);
                } finally {
                    btnConfirmMermaSave.disabled = false;
                    btnConfirmMermaSave.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Confirmar y Guardar';
                    pendingSave = null;
                }
            });
        }
    });
})();