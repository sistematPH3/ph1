document.addEventListener('DOMContentLoaded', () => {
    const locationElement = document.getElementById('location_id');
    const wasteTypeSelect = document.getElementById('waste_type_id');
    const itemTypeSelect = document.getElementById('item_type_id');
    const productSelect = document.getElementById('product_id');
    const lotSelect = document.getElementById('lot_number');
    const quantityInput = document.getElementById('quantity');
    const quantityHint = document.getElementById('quantityHint');
    const notesInput = document.getElementById('notes');
    const alertContainer = document.getElementById('alertContainer');
    const btnAddToList = document.getElementById('btnAddToList');
    const cardsGrid = document.getElementById('cardsGrid');
    const btnSubmitMerma = document.getElementById('btnSubmitMerma');
    const cartCountBadge = document.getElementById('cartCountBadge');
    const submitSummary = document.getElementById('submitSummary');
    const locationLockHint = document.getElementById('locationLockHint');
    const addFeedback = document.getElementById('addFeedback');
    const editorAlert = document.getElementById('editorAlert');
    const submitAlert = document.getElementById('submitAlert');
    const vencidoNote = document.getElementById('vencidoNote');

    const photoInput = document.getElementById('photoInput');
    const dropzone = document.getElementById('dropzone');
    const photoPreviewWrap = document.getElementById('photoPreviewWrap');
    const photoPreview = document.getElementById('photoPreview');
    const photoState = document.getElementById('photoState');
    const btnRemovePhoto = document.getElementById('btnRemovePhoto');
    const evidenceUrlInput = document.getElementById('evidence_url');

    const itemDropzone = document.getElementById('itemDropzone');
    const itemPhotoInput = document.getElementById('itemPhotoInput');
    const itemPhotosList = document.getElementById('itemPhotosList');
    const ticketEmpty = document.getElementById('ticketEmpty');
    const qtyMinus = document.getElementById('qtyMinus');
    const qtyPlus = document.getElementById('qtyPlus');

    let cartItems = [];
    let currentLotsData = [];
    let currentProductsData = [];
    let currentItemPhotoUrls = [];
    let currentVencidos = [];
    let lotsSeq = 0;
    let pendingRequestId = null;

    const lockedTypeCode = (document.getElementById('locked_type_code') || {}).value || null;
    const wasteTypesByOption = {};
    let wasteTypesData = [];
    const isSingleLocation = !locationElement || locationElement.tagName === 'INPUT';

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function scheduleDismiss(el, ms) {
        if (!el) return;
        setTimeout(() => {
            if (el.isConnected && !el.classList.contains('merma-alert-leaving')) {
                el.classList.add('merma-alert-leaving');
                setTimeout(() => { if (el && el.isConnected) el.remove(); }, 400);
            }
        }, ms);
    }

    function showAlert(type, message) {
        const icon = type === 'success' ? 'bi-check-circle-fill'
            : type === 'danger' ? 'bi-exclamation-triangle-fill'
                : 'bi-info-circle-fill';
        alertContainer.innerHTML = `
            <div class="alert alert-${type} alert-dismissible fade show shadow-sm" role="alert">
                <i class="bi ${icon} me-2"></i> ${escapeHtml(message)}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
        scheduleDismiss(alertContainer.lastElementChild, type === 'success' ? 3500 : 6000);
    }

    function showInlineAlert(container, type, message) {
        if (!container) { showAlert(type, message); return; }
        const icons = {
            success: 'bi-check-circle-fill',
            danger: 'bi-exclamation-triangle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill'
        };
        container.innerHTML = `
            <div class="alert alert-${type} merma-inline-alert fade show" role="alert">
                <i class="bi ${icons[type] || 'bi-info-circle-fill'} me-2"></i>${escapeHtml(message)}
            </div>
        `;
        scheduleDismiss(container.firstElementChild, type === 'success' ? 3500 : 6000);
    }

    const showEditorAlert = (type, message) => showInlineAlert(editorAlert, type, message);
    const showSubmitAlert = (type, message) => showInlineAlert(submitAlert, type, message);

    function currentLocationId() {
        if (!locationElement) return null;
        return locationElement.value;
    }

    const selectedTypeCode = () => {
        if (!wasteTypeSelect || !wasteTypeSelect.value) return null;
        return wasteTypesByOption[String(wasteTypeSelect.value)] || null;
    };

    // Tipo de merma del insumo que se está editando (por defecto, el del ticket).
    const itemTypeCode = () => {
        if (!itemTypeSelect || !itemTypeSelect.value || !wasteTypesData.length) return null;
        const found = wasteTypesData.find(t => String(t.id) === String(itemTypeSelect.value));
        return found ? found.code : null;
    };

    // Modo "VENCIDO" efectivo: lo activa el tipo del ticket O el del insumo.
    const effectiveVencidoMode = () =>
        selectedTypeCode() === 'VENCIDO' || itemTypeCode() === 'VENCIDO';

    const populateItemTypeSelect = () => {
        if (!itemTypeSelect) return;
        const headerVal = wasteTypeSelect ? wasteTypeSelect.value : '';
        itemTypeSelect.innerHTML = '';
        if (!headerVal || wasteTypesData.length === 0) {
            itemTypeSelect.innerHTML = '<option value="" selected disabled>Esperando tipo del ticket...</option>';
            itemTypeSelect.disabled = true;
            return;
        }
        wasteTypesData.forEach(t => {
            const option = document.createElement('option');
            option.value = t.id;
            option.textContent = t.name + (t.requires_approval ? ' (requiere aprobación)' : '');
            itemTypeSelect.appendChild(option);
        });
        const stillValid = wasteTypesData.some(t => String(t.id) === String(itemTypeSelect.value));
        if (!stillValid) {
            itemTypeSelect.value = headerVal;
        }
        itemTypeSelect.disabled = false;
    };

    const hasExpiredDate = (expirationDateText) => {
        if (!expirationDateText) return false;
        const parts = String(expirationDateText).split('/');
        if (parts.length !== 3) return false;
        const day = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10);
        const year = parseInt(parts[2], 10);
        if (!day || !month || !year) return false;
        const parsed = new Date(year, month - 1, day);
        if (isNaN(parsed.getTime())) return false;
        const today = new Date();
        const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        return parsed < todayStart;
    };

    const loadWasteTypes = async (locationId) => {
        if (!wasteTypeSelect) return;
        wasteTypeSelect.innerHTML = '<option value="" selected disabled>Cargando tipos...</option>';
        wasteTypeSelect.disabled = true;
        Object.keys(wasteTypesByOption).forEach(k => delete wasteTypesByOption[k]);
        if (itemTypeSelect) {
            itemTypeSelect.innerHTML = '<option value="" selected disabled>Esperando tipo del ticket...</option>';
            itemTypeSelect.disabled = true;
        }
        try {
            const response = await fetch(`/api/waste/locations/${locationId}/types`);
            const result = await response.json();
            if (response.ok && result.success) {
                wasteTypesData = Array.isArray(result.types) ? result.types : [];
                wasteTypeSelect.innerHTML = '<option value="" selected disabled>Seleccione el tipo de merma...</option>';
                let foundLocked = false;
                result.types.forEach(t => {
                    const option = document.createElement('option');
                    option.value = t.id;
                    const reqLabel = (t.requires_approval) ? ' (requiere aprobación)' : '';
                    option.textContent = `${t.name}${reqLabel}`;
                    wasteTypeSelect.appendChild(option);
                    wasteTypesByOption[String(t.id)] = t.code;
                    if (lockedTypeCode && t.code === lockedTypeCode) {
                        wasteTypeSelect.value = String(t.id);
                        foundLocked = true;
                    }
                });
                if (lockedTypeCode) {
                    if (foundLocked) {
                        wasteTypeSelect.disabled = true;
                    } else {
                        showAlert('warning', `El tipo "${lockedTypeCode}" no aplica para esta sede.`);
                        wasteTypeSelect.disabled = false;
                    }
                } else {
                    wasteTypeSelect.disabled = false;
                }
                populateItemTypeSelect();
                updateSteps();
            }
        } catch (e) {
            wasteTypeSelect.innerHTML = '<option value="" selected disabled>Error al cargar tipos</option>';
        }
    };

    const loadProducts = async (locationId, filterVencidos) => {
        productSelect.innerHTML = '<option value="" selected disabled>Buscando inventario...</option>';
        productSelect.disabled = true;
        lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
        lotSelect.disabled = true;
        quantityInput.disabled = true;
        quantityInput.value = '';
        quantityInput.max = '999999.99';
        quantityHint.textContent = '';
        quantityHint.classList.remove('text-danger');
        btnAddToList.disabled = true;
        currentProductsData = [];

        try {
            const response = await fetch(`/api/waste/locations/${locationId}/products`);
            const result = await response.json();
            if (response.ok && result.success) {
                let products = result.products || [];
                let emptyMessage = 'Sin inventario en esta sede';

                if (filterVencidos) {
                    const expiredIds = new Set(currentVencidos.map(v => v.product_id));
                    products = products.filter(p => expiredIds.has(p.id));
                    emptyMessage = 'Sin insumos vencidos en esta sede';
                }

                productSelect.innerHTML = '<option value="" selected disabled>Seleccione un producto...</option>';
                currentProductsData = products;
                currentProductsData.forEach(p => {
                    const option = document.createElement('option');
                    option.value = p.id;
                    option.textContent = p.name;
                    productSelect.appendChild(option);
                });

                if (vencidoNote) {
                    if (filterVencidos) {
                        if (currentProductsData.length === 0) {
                            vencidoNote.textContent = 'No hay insumos vencidos con stock en esta sede.';
                            vencidoNote.className = 'merma-editor-note text-expired';
                            vencidoNote.classList.remove('d-none');
                        } else {
                            vencidoNote.textContent = 'Modo vencido: solo se listan los insumos vencidos.';
                            vencidoNote.className = 'merma-editor-note text-info';
                            vencidoNote.classList.remove('d-none');
                        }
                    } else {
                        vencidoNote.classList.add('d-none');
                        vencidoNote.textContent = '';
                    }
                }

                if (currentProductsData.length === 0) {
                    productSelect.innerHTML = `<option value="" selected disabled>${emptyMessage}</option>`;
                    if (filterVencidos) {
                        showEditorAlert('warning', emptyMessage + '. Registra otra categoría de merma si no hay vencimientos.');
                    } else {
                        showAlert('warning', 'No hay insumos con stock en esta sede.');
                    }
                    productSelect.disabled = false;
                    return;
                }
                productSelect.disabled = false;
            }
        } catch (e) {
            productSelect.innerHTML = '<option value="" selected disabled>Error de conexión</option>';
        }
    };

    const loadVencidos = async (locationId) => {
        currentVencidos = [];
        try {
            const response = await fetch(`/api/waste/locations/${locationId}/vencidos`);
            const result = await response.json();
            if (response.ok && result.success) {
                currentVencidos = Array.isArray(result.vencidos) ? result.vencidos : [];
            }
        } catch (e) {
            currentVencidos = [];
        }
    };

    const refreshProducts = (locationId) => {
        if (!locationId) return;
        if (effectiveVencidoMode()) {
            loadVencidos(locationId).then(() => loadProducts(locationId, true));
        } else {
            loadProducts(locationId, false);
        }
    };

    const loadLots = async (locationId, productId) => {
        lotSelect.innerHTML = '<option value="" selected disabled>Cargando lotes...</option>';
        lotSelect.disabled = true;
        currentLotsData = [];
        const seq = ++lotsSeq;

        try {
            const response = await fetch(`/api/waste/locations/${locationId}/products/${productId}/lots`);
            const result = await response.json();
            if (seq !== lotsSeq) return;
            if (response.ok && result.success) {
                currentLotsData = Array.isArray(result.lots) ? result.lots : [];
                if (effectiveVencidoMode()) {
                    currentLotsData = currentLotsData.filter(l =>
                        hasExpiredDate(l.expiration_date));
                }
                lotSelect.innerHTML = '';
                if (currentLotsData.length === 0) {
                    lotSelect.innerHTML = '<option value="" selected disabled>Sin lotes con saldo</option>';
                    lotSelect.disabled = true;
                    quantityInput.disabled = true;
                    btnAddToList.disabled = true;
                    return;
                }
                const firstOption = document.createElement('option');
                firstOption.value = '';
                firstOption.textContent = 'Seleccione un lote...';
                firstOption.selected = true;
                firstOption.disabled = true;
                lotSelect.appendChild(firstOption);
                currentLotsData.forEach(lot => {
                    const option = document.createElement('option');
                    option.value = lot.lot_number;
                    option.textContent = `${lot.lot_number} (Vence: ${lot.expiration_date} | Disp: ${lot.quantity})`;
                    lotSelect.appendChild(option);
                });
                lotSelect.disabled = false;
            }
        } catch (e) {
            lotSelect.innerHTML = '<option value="" selected disabled>Error al cargar lotes</option>';
        }
    };

    const usedQtyForLot = (lotNumber) =>
        cartItems
            .filter(item => item.lot_number === lotNumber)
            .reduce((sum, item) => sum + item.quantity, 0);

    const availableQtyForLot = (lotNumber) => {
        const lot = currentLotsData.find(l => l.lot_number === lotNumber);
        if (!lot || lot.quantity == null) return null;
        const base = parseFloat(lot.quantity);
        if (isNaN(base)) return null;
        return base - usedQtyForLot(lotNumber);
    };

    const sanitizeQuantity = () => {
        const raw = quantityInput.value;
        if (raw === '' || raw === '.') {
            validateQuantity();
            return;
        }
        const v = parseFloat(raw);
        if (isNaN(v)) {
            quantityInput.value = '';
            validateQuantity();
            return;
        }
        const lotVal = lotSelect.value;
        const avail = lotVal ? availableQtyForLot(lotVal) : null;
        if (avail != null && avail > 0 && v > avail) {
            quantityInput.value = String(parseFloat(avail.toFixed(2)));
            quantityHint.classList.remove('text-danger');
            quantityInput.classList.remove('is-invalid');
            quantityHint.textContent = `Se ajustó al saldo del lote (${avail.toFixed(2)}).`;
            return;
        }
        validateQuantity();
    };

    const validateQuantity = () => {
        const lotVal = lotSelect.value;
        quantityHint.classList.remove('text-danger');
        quantityInput.classList.remove('is-invalid');
        if (!lotVal) {
            quantityHint.textContent = '';
            return;
        }
        const avail = availableQtyForLot(lotVal);
        const raw = quantityInput.value;
        const v = parseFloat(raw);
        if (avail == null) {
            quantityHint.textContent = '';
            return;
        }
        if (raw === '') {
            quantityHint.textContent = `Disponible: ${avail.toFixed(2)}`;
            return;
        }
        if (isNaN(v) || v <= 0) {
            quantityHint.textContent = 'Cantidad inválida.';
            quantityHint.classList.add('text-danger');
            quantityInput.classList.add('is-invalid');
            return;
        }
        if (v > avail) {
            quantityHint.textContent = `Supera el saldo del lote (disponible: ${avail.toFixed(2)}).`;
            quantityHint.classList.add('text-danger');
            quantityInput.classList.add('is-invalid');
        }
    };

    const updateQuantityConstraint = () => {
        const lotVal = lotSelect ? lotSelect.value : '';
        if (!lotVal) {
            quantityInput.disabled = true;
            quantityInput.value = '';
            quantityInput.max = '999999.99';
            quantityHint.textContent = '';
            quantityHint.classList.remove('text-danger');
            quantityInput.classList.remove('is-invalid');
            btnAddToList.disabled = true;
            return;
        }
        const avail = availableQtyForLot(lotVal);
        if (avail != null && avail <= 0) {
            quantityInput.disabled = true;
            quantityInput.value = '';
            quantityInput.max = '999999.99';
            quantityHint.textContent = `Lote agotado (saldo disponible: 0.00). Elige otro lote.`;
            quantityHint.classList.add('text-danger');
            quantityInput.classList.remove('is-invalid');
            btnAddToList.disabled = true;
            return;
        }
        quantityInput.disabled = false;
        quantityInput.max = (avail != null && avail > 0) ? avail : '0.01';
        quantityInput.min = '0.01';
        btnAddToList.disabled = false;
        validateQuantity();
    };

    const updateSteps = () => {
        const steps = document.querySelectorAll('.merma-step');
        if (!steps.length) return;
        const step1Done = !!(currentLocationId() && wasteTypeSelect && wasteTypeSelect.value);
        const step2Done = cartItems.length > 0;
        const step3Done = !!(notesInput && notesInput.value.trim());
        const active = !step1Done ? 1 : (!step2Done ? 2 : (!step3Done ? 3 : 3));
        const allDone = step1Done && step2Done && step3Done;
        steps.forEach(s => {
            const n = parseInt(s.dataset.step, 10);
            const ownDone = n === 1 ? step1Done : (n === 2 ? step2Done : step3Done);
            s.classList.toggle('is-done', ownDone && (n < active || allDone));
            s.classList.toggle('is-active', n === active);
        });
    };

    const renderCards = () => {
        const total = cartItems.length;
        cartCountBadge.textContent = total === 1 ? '1 añadido' : `${total} añadidos`;
        cartCountBadge.classList.toggle('d-none', total === 0);
        if (ticketEmpty) ticketEmpty.classList.toggle('d-none', total !== 0);

        if (submitSummary) {
            if (total === 0) {
                submitSummary.classList.add('d-none');
                submitSummary.textContent = '0';
            } else {
                const totalQty = cartItems.reduce((s, i) => s + i.quantity, 0);
                submitSummary.textContent = `${totalQty.toFixed(2)} unidades`;
                submitSummary.classList.remove('d-none');
            }
        }

        cardsGrid.innerHTML = '';
        cartItems.forEach((item, index) => {
            const card = document.createElement('div');
            card.className = 'merma-card';
            card.dataset.index = index;
            const photos = (item.evidence_urls && item.evidence_urls.length)
                ? item.evidence_urls
                : (item.evidence_url ? [item.evidence_url] : []);
            const firstUrl = photos[0] || null;
            const photoHtml = firstUrl
                ? `<img src="${escapeHtml(firstUrl)}" alt="Foto del ítem" class="merma-card-photo-img" onclick="window.open('${escapeHtml(firstUrl)}', '_blank')">`
                : `<div class="merma-card-photo-empty"><i class="bi bi-image"></i></div>`;
            const thumbsHtml = photos.slice(firstUrl ? 1 : 0).map(u => `
                <img src="${escapeHtml(u)}" alt="Foto del ítem" class="merma-card-thumb"
                     title="Ver foto" onclick="window.open('${escapeHtml(u)}', '_blank')">
            `).join('');
            const countBadge = photos.length > 1
                ? `<span class="badge rounded-pill bg-danger-subtle text-danger border border-danger-subtle">${photos.length} fotos</span>`
                : '';
            const expired = hasExpiredDate(item.expiration_date);
            let tipoBadge = '';
            if (item.waste_type_id && wasteTypesData.length) {
                const t = wasteTypesData.find(x => String(x.id) === String(item.waste_type_id));
                if (t) tipoBadge = '<span class="badge rounded-pill bg-light text-dark border"><i class="bi bi-tag me-1"></i>' + escapeHtml(t.name) + '</span>';
            }
            card.innerHTML = `
                <button type="button" class="merma-card-remove" title="Quitar este insumo" onclick="removeMermaItem(${index})">
                    <i class="bi bi-x-lg"></i>
                </button>
                <div class="merma-card-photo">${photoHtml}</div>
                <div class="merma-card-body">
                    <div class="merma-card-name">${escapeHtml(item.product_name)}</div>
                    <div class="merma-card-badges">
                        ${tipoBadge}
                        <span class="badge rounded-pill bg-light text-dark border font-monospace">Lote ${escapeHtml(item.lot_number)}</span>
                        <span class="badge rounded-pill ${expired ? 'bg-danger-subtle text-danger border border-danger-subtle' : 'bg-light text-muted border'}" title="Vencimiento">
                            Vence: ${escapeHtml(item.expiration_date || '—')}
                        </span>
                        ${countBadge}
                    </div>
                    <div class="merma-card-qty">Cantidad: <strong>${item.quantity.toFixed(2)}</strong></div>
                    ${thumbsHtml ? `<div class="merma-card-thumbs">${thumbsHtml}</div>` : ''}
                </div>
            `;
            cardsGrid.appendChild(card);
        });

        updateLocationLock();
        updateSteps();
    };

    window.removeMermaItem = (index) => {
        cartItems.splice(index, 1);
        updateLocationLock();
        renderCards();
    };

    const updateLocationLock = () => {
        if (!locationElement || locationElement.tagName !== 'SELECT') return;
        const blocked = cartItems.length > 0;
        locationElement.disabled = blocked;
        if (locationLockHint) locationLockHint.classList.toggle('d-none', !blocked);
    };

    const resetEditor = () => {
        productSelect.value = '';
        lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
        lotSelect.disabled = true;
        quantityInput.value = '';
        quantityInput.disabled = true;
        quantityInput.max = '999999.99';
        quantityHint.textContent = '';
        quantityHint.classList.remove('text-danger');
        quantityInput.classList.remove('is-invalid');
        btnAddToList.disabled = true;
        resetItemPhoto();
        currentLotsData = [];
    };

    const flashFeedback = () => {
        addFeedback.classList.remove('d-none');
        addFeedback.classList.remove('merma-feedback-out');
        void addFeedback.offsetWidth;
        addFeedback.classList.add('merma-feedback-in');
        setTimeout(() => {
            addFeedback.classList.remove('merma-feedback-in');
            addFeedback.classList.add('merma-feedback-out');
            setTimeout(() => addFeedback.classList.add('d-none'), 450);
        }, 2200);
    };

    btnAddToList.addEventListener('click', () => {
        alertContainer.innerHTML = '';
        if (editorAlert) editorAlert.innerHTML = '';

        const locId = currentLocationId();
        const wasteTypeId = +wasteTypeSelect.value;
        const productId = +productSelect.value;
        const productName = productSelect.options[productSelect.selectedIndex]?.text;
        const lotVal = lotSelect ? lotSelect.value : '';
        const qty = parseFloat(quantityInput.value);

        if (!locId) { showEditorAlert('warning', 'Debe seleccionar la sede en el paso 1.'); return; }
        if (!wasteTypeId) { showEditorAlert('warning', 'Debe seleccionar el tipo de merma en el paso 1.'); return; }
        if (isNaN(productId) || isNaN(qty) || qty <= 0) {
            showEditorAlert('warning', 'Debe seleccionar un producto y una cantidad mayor a 0.');
            return;
        }
        if (!lotVal) {
            showEditorAlert('warning', 'Debe seleccionar el lote específico del producto.');
            return;
        }

        const avail = availableQtyForLot(lotVal);
        if (avail != null && qty > avail) {
            showEditorAlert('warning', `El lote ${lotVal} solo dispone de ${avail.toFixed(2)} unidades.`);
            quantityInput.focus();
            return;
        }

        const itemTypeId = (itemTypeSelect && itemTypeSelect.value) ? +itemTypeSelect.value : null;
        const lotObj = currentLotsData.find(l => l.lot_number === lotVal);

        cartItems.push({
            product_id: productId,
            product_name: productName,
            lot_number: lotVal,
            quantity: qty,
            waste_type_id: itemTypeId,
            expiration_date: (lotObj && lotObj.expiration_date) ? lotObj.expiration_date : null,
            evidence_urls: currentItemPhotoUrls.slice(),
            evidence_url: currentItemPhotoUrls[0] || null
        });

        resetEditor();
        renderCards();
        flashFeedback();
        if (productSelect) productSelect.focus();
    });

    const resetItemPhoto = () => {
        currentItemPhotoUrls = [];
        itemPhotosList.innerHTML = '';
        itemPhotosList.classList.add('d-none');
        itemPhotoInput.value = '';
    };

    const renderItemPhotosList = () => {
        itemPhotosList.classList.toggle('d-none', currentItemPhotoUrls.length === 0);
    };

    const addItemPhotoCard = (file) => {
        const el = document.createElement('div');
        el.className = 'merma-itemphoto';
        el.innerHTML = `
            <img src="${URL.createObjectURL(file)}" alt="Subiendo..." class="merma-itemphoto-img">
            <span class="merma-itemphoto-spinner"><i class="bi bi-arrow-repeat"></i></span>
            <button type="button" class="merma-itemphoto-remove" title="Quitar esta foto">
                <i class="bi bi-x"></i>
            </button>
        `;
        el.querySelector('.merma-itemphoto-remove').addEventListener('click', () => {
            const url = el.dataset.url;
            if (url) {
                currentItemPhotoUrls = currentItemPhotoUrls.filter(u => u !== url);
            }
            el.remove();
            renderItemPhotosList();
        });
        itemPhotosList.appendChild(el);
        return el;
    };

    const uploadItemPhoto = async (file, el) => {
        const formData = new FormData();
        formData.append('image', file);
        try {
            const response = await fetch('/api/waste/evidence', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (response.ok && result.success && result.url) {
                if (!el.isConnected) return;
                el.dataset.url = result.url;
                el.querySelector('img').src = result.url;
                el.querySelector('.merma-itemphoto-spinner').remove();
                currentItemPhotoUrls.push(result.url);
                renderItemPhotosList();
            } else {
                el.remove();
                showAlert('warning', 'Una foto del ítem no se pudo cargar; puede continuar sin ella.');
            }
        } catch (e) {
            el.remove();
            showAlert('warning', 'Error al subir una foto del ítem; puede continuar sin ella.');
        }
    };

    const handleItemPhotoFiles = (files) => {
        if (!files || files.length === 0) return;
        let images = [];
        let nonImages = 0;
        Array.from(files).forEach(file => {
            if (!file.type || !file.type.startsWith('image/')) { nonImages++; return; }
            images.push(file);
        });
        if (nonImages > 0) {
            showAlert('warning', 'Solo se permiten archivos de imagen.');
        }
        const limit = 10;
        const slots = limit - currentItemPhotoUrls.length;
        if (slots <= 0 || images.length === 0) {
            if (slots <= 0 && images.length > 0) {
                showAlert('warning', 'Máximo 10 fotos por producto.');
            }
            return;
        }
        if (images.length > slots) {
            showAlert('warning',
                `Máximo 10 fotos por producto: se subirán ${slots} de ${images.length} seleccionadas.`);
            images = images.slice(0, slots);
        }
        itemPhotosList.classList.remove('d-none');
        images.forEach(file => {
            const el = addItemPhotoCard(file);
            uploadItemPhoto(file, el);
        });
    };

    if (itemPhotoInput && itemDropzone) {
        itemDropzone.addEventListener('click', () => itemPhotoInput.click());
        itemDropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            itemDropzone.classList.add('dragover');
        });
        itemDropzone.addEventListener('dragleave', () => itemDropzone.classList.remove('dragover'));
        itemDropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            itemDropzone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                itemPhotoInput.files = e.dataTransfer.files;
                handleItemPhotoFiles(e.dataTransfer.files);
            }
        });
        itemPhotoInput.addEventListener('change', () => {
            if (itemPhotoInput.files && itemPhotoInput.files.length > 0) {
                handleItemPhotoFiles(itemPhotoInput.files);
            }
        });
    }

    const resetPhotoDropzone = () => {
        dropzone.classList.remove('d-none');
        photoPreviewWrap.classList.add('d-none');
        if (photoPreview) photoPreview.removeAttribute('src');
        evidenceUrlInput.value = '';
    };

    let photoUploadSeq = 0;

    const handlePhotoFile = (file) => {
        if (!file) return;
        if (!file.type || !file.type.startsWith('image/')) {
            showAlert('warning', 'Solo se permiten archivos de imagen.');
            return;
        }
        const seq = ++photoUploadSeq;
        dropzone.classList.add('d-none');
        photoPreviewWrap.classList.remove('d-none');
        photoPreview.src = URL.createObjectURL(file);
        photoState.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>Subiendo...';
        photoState.classList.remove('text-success');
        uploadPhoto(file, seq);
    };

    const uploadPhoto = async (file, seq) => {
        const formData = new FormData();
        formData.append('image', file);
        try {
            const response = await fetch('/api/waste/evidence', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (response.ok && result.success && result.url) {
                if (seq !== photoUploadSeq) return;
                if (photoPreviewWrap.classList.contains('d-none')) return;
                evidenceUrlInput.value = result.url;
                photoState.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i>Foto adjuntada';
                photoState.classList.add('text-success');
            } else {
                photoState.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>No se pudo subir';
                showAlert('warning', 'La foto general no se pudo cargar, pero puede continuar sin ella.');
            }
        } catch (e) {
            photoState.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Error de conexión';
            showAlert('warning', 'Error al subir la foto general; puede continuar sin ella.');
        }
    };

    if (photoInput && dropzone) {
        dropzone.addEventListener('click', () => photoInput.click());
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                photoInput.files = e.dataTransfer.files;
                handlePhotoFile(e.dataTransfer.files[0]);
            }
        });
        photoInput.addEventListener('change', () => {
            if (photoInput.files && photoInput.files.length > 0) {
                handlePhotoFile(photoInput.files[0]);
            }
        });
    }

    if (btnRemovePhoto) {
        btnRemovePhoto.addEventListener('click', () => {
            resetPhotoDropzone();
            if (photoInput) photoInput.value = '';
        });
    }

    if (locationElement && locationElement.tagName === 'SELECT') {
        locationElement.addEventListener('change', (e) => {
            if (locationElement.disabled) return;
            cartItems = [];
            resetEditor();
            renderCards();
            loadWasteTypes(e.target.value).then(() => refreshProducts(e.target.value));
        });
    }

    if (productSelect) {
        productSelect.addEventListener('change', (e) => {
            const locId = currentLocationId();
            const prodId = parseInt(e.target.value);
            if (!isNaN(prodId) && locId) {
                loadLots(locId, prodId);
            } else {
                quantityInput.disabled = true;
                btnAddToList.disabled = true;
            }
        });
    }

    if (lotSelect) {
        lotSelect.addEventListener('change', updateQuantityConstraint);
    }

    if (quantityInput) {
        quantityInput.addEventListener('keydown', (e) => {
            if (['e', 'E', '+', '-'].includes(e.key)) {
                e.preventDefault();
            }
        });
        quantityInput.addEventListener('input', sanitizeQuantity);
    }

    const stepQuantity = (delta) => {
        if (!quantityInput || quantityInput.disabled) return;
        const cur = parseFloat(quantityInput.value);
        const next = (isNaN(cur) ? 0 : cur) + delta;
        quantityInput.value = (next >= 0.01 ? next : 0.01).toFixed(2);
        sanitizeQuantity();
    };

    if (qtyMinus) {
        qtyMinus.addEventListener('click', () => stepQuantity(-0.5));
    }
    if (qtyPlus) {
        qtyPlus.addEventListener('click', () => stepQuantity(0.5));
    }

    if (wasteTypeSelect) {
        wasteTypeSelect.addEventListener('change', () => {
            const locId = currentLocationId();
            resetEditor();
            updateSteps();
            populateItemTypeSelect();
            refreshProducts(locId);
        });
    }

    if (itemTypeSelect) {
        itemTypeSelect.addEventListener('change', () => {
            const locId = currentLocationId();
            resetEditor();
            refreshProducts(locId);
        });
    }

    if (notesInput) {
        notesInput.addEventListener('input', updateSteps);
    }

    if (isSingleLocation && currentLocationId()) {
        loadWasteTypes(currentLocationId()).then(() => refreshProducts(currentLocationId()));
    }

    btnSubmitMerma.addEventListener('click', async () => {
        if (submitAlert) submitAlert.innerHTML = '';

        if (cartItems.length === 0) {
            showSubmitAlert('warning', 'Agrega al menos un insumo al ticket antes de registrar.');
            return;
        }

        const locId = currentLocationId();
        const wasteTypeId = +wasteTypeSelect.value;
        const notes = notesInput.value.trim();

        if (!wasteTypeId) { showSubmitAlert('warning', 'Debe seleccionar el tipo de merma en el paso 1.'); return; }
        if (!notes) { showSubmitAlert('warning', 'Falta el motivo de la merma: complétalo en el paso 3.'); return; }

        const originalHtml = btnSubmitMerma.innerHTML;
        btnSubmitMerma.disabled = true;
        btnSubmitMerma.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Procesando...';

        if (!pendingRequestId) {
            pendingRequestId = 'waste-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
        }

        const payload = {
            location_id: parseInt(locId),
            waste_type_id: wasteTypeId,
            notes: notes,
            request_id: pendingRequestId,
            evidence_url: evidenceUrlInput.value || null,
            items: cartItems.map(item => ({
                product_id: item.product_id,
                lot_number: item.lot_number,
                quantity: item.quantity,
                waste_type_id: (item.waste_type_id != null) ? item.waste_type_id : null,
                evidence_urls: (item.evidence_urls && item.evidence_urls.length) ? item.evidence_urls : null,
                evidence_url: item.evidence_url || null
            }))
        };

        try {
            const response = await fetch('/waste/merma/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (response.ok && result.success) {
                cartItems = [];
                pendingRequestId = null;
                resetEditor();
                renderCards();
                notesInput.value = '';
                updateSteps();
                resetPhotoDropzone();
                if (photoInput) photoInput.value = '';
                showSubmitAlert('success', result.message);
                if (locationElement && locationElement.tagName === 'SELECT') {
                    refreshProducts(locationElement.value);
                    loadWasteTypes(locationElement.value);
                } else {
                    refreshProducts(currentLocationId());
                    loadWasteTypes(currentLocationId());
                }
            } else {
                let errorText = result.message || 'Error al registrar la merma.';
                if (result.errors) {
                    errorText = Object.entries(result.errors).map(([k, v]) => `${v}`).join(' · ');
                }
                showSubmitAlert('danger', errorText);
            }
        } catch (e) {
            showSubmitAlert('danger', 'Error de conexión con el servidor.');
        } finally {
            btnSubmitMerma.innerHTML = originalHtml;
            btnSubmitMerma.disabled = false;
        }
    });
});