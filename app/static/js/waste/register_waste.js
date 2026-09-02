document.addEventListener('DOMContentLoaded', () => {
    const locationElement = document.getElementById('location_id');
    const wasteTypeSelect = document.getElementById('waste_type_id');
    const productSelect = document.getElementById('product_id');
    const lotSelect = document.getElementById('lot_number');
    const quantityInput = document.getElementById('quantity');
    const notesInput = document.getElementById('notes');
    const alertContainer = document.getElementById('alertContainer');
    const btnAddToList = document.getElementById('btnAddToList');
    const cartSection = document.getElementById('cartSection');
    const cartBody = document.getElementById('cartBody');
    const btnSubmitMerma = document.getElementById('btnSubmitMerma');

    const photoInput = document.getElementById('photoInput');
    const dropzone = document.getElementById('dropzone');
    const dropzoneInner = document.getElementById('dropzoneInner');
    const photoPreviewWrap = document.getElementById('photoPreviewWrap');
    const photoPreview = document.getElementById('photoPreview');
    const photoState = document.getElementById('photoState');
    const btnRemovePhoto = document.getElementById('btnRemovePhoto');
    const evidenceUrlInput = document.getElementById('evidence_url');

    let cartItems = [];
    let currentLotsData = [];
    let currentProductsData = [];

    const isSingleLocation = !locationElement || locationElement.tagName === 'INPUT';

    function showAlert(type, message) {
        const icon = type === 'success' ? 'bi-check-circle-fill'
            : type === 'danger' ? 'bi-exclamation-triangle-fill'
            : 'bi-info-circle-fill';
        alertContainer.innerHTML = `
            <div class="alert alert-${type} alert-dismissible fade show shadow-sm" role="alert">
                <i class="bi ${icon} me-2"></i> ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
    }

    function currentLocationId() {
        if (!locationElement) return null;
        return locationElement.tagName === 'SELECT' ? locationElement.value : locationElement.value;
    }

    // ====== TIPOS DE MERMA POR SEDE ======
    const loadWasteTypes = async (locationId) => {
        if (!wasteTypeSelect) return;
        wasteTypeSelect.innerHTML = '<option value="" selected disabled>Cargando tipos...</option>';
        wasteTypeSelect.disabled = true;
        try {
            const response = await fetch(`/api/waste/locations/${locationId}/types`);
            const result = await response.json();
            if (response.ok && result.success) {
                wasteTypeSelect.innerHTML = '<option value="" selected disabled>Seleccione el tipo de merma...</option>';
                result.types.forEach(t => {
                    const option = document.createElement('option');
                    option.value = t.id;
                    const reqLabel = (t.code === 'TEMPERATURA' || t.code === 'ROBO_SOSPECHA') ? ' (requiere aprobación)' : '';
                    option.textContent = `${t.name}${reqLabel}`;
                    wasteTypeSelect.appendChild(option);
                });
                wasteTypeSelect.disabled = false;
            }
        } catch (e) {
            wasteTypeSelect.innerHTML = '<option value="" selected disabled>Error al cargar tipos</option>';
        }
    };

    // ====== PRODUCTOS ======
    const loadProducts = async (locationId) => {
        productSelect.innerHTML = '<option value="" selected disabled>Buscando inventario...</option>';
        productSelect.disabled = true;
        if (lotSelect) {
            lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
            lotSelect.disabled = true;
        }
        quantityInput.disabled = true;
        btnAddToList.disabled = true;
        quantityInput.value = '';
        currentProductsData = [];

        try {
            const response = await fetch(`/api/waste/locations/${locationId}/products`);
            const result = await response.json();
            if (response.ok && result.success) {
                productSelect.innerHTML = '<option value="" selected disabled>Seleccione un producto...</option>';
                currentProductsData = result.products || [];

                if (currentProductsData.length === 0) {
                    productSelect.innerHTML = '<option value="" selected disabled>Sin inventario en esta sede</option>';
                    showAlert('warning', 'No hay insumos con stock en esta sede.');
                } else {
                    currentProductsData.forEach(p => {
                        const option = document.createElement('option');
                        option.value = p.id;
                        option.textContent = p.name;
                        productSelect.appendChild(option);
                    });
                    productSelect.disabled = false;
                }
            }
        } catch (e) {
            productSelect.innerHTML = '<option value="" selected disabled>Error de conexión</option>';
        }
    };

    // ====== LOTES ======
    const loadLots = async (locationId, productId) => {
        if (!lotSelect) return;
        lotSelect.innerHTML = '<option value="" selected disabled>Cargando lotes...</option>';
        lotSelect.disabled = true;
        currentLotsData = [];

        try {
            const response = await fetch(`/api/waste/locations/${locationId}/products/${productId}/lots`);
            const result = await response.json();
            if (response.ok && result.success) {
                currentLotsData = Array.isArray(result.lots) ? result.lots : [];
                lotSelect.innerHTML = '';

                if (currentLotsData.length === 0) {
                    lotSelect.innerHTML = '<option value="" selected disabled>Sin lotes con saldo</option>';
                    lotSelect.disabled = true;
                    quantityInput.disabled = true;
                    btnAddToList.disabled = true;
                } else {
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
                        option.dataset.maxQuantity = lot.quantity;
                        lotSelect.appendChild(option);
                    });
                    lotSelect.disabled = false;
                }
            }
        } catch (e) {
            lotSelect.innerHTML = '<option value="" selected disabled>Error al cargar lotes</option>';
        }
    };

    const updateQuantityConstraint = () => {
        const lotVal = lotSelect ? lotSelect.value : '';
        if (!lotVal) {
            quantityInput.disabled = true;
            btnAddToList.disabled = true;
            return;
        }
        quantityInput.disabled = false;
        btnAddToList.disabled = false;
    };

    // ====== INICIO: precargar si hay sede única ======
    if (isSingleLocation && currentLocationId()) {
        loadWasteTypes(currentLocationId());
        loadProducts(currentLocationId());
    }

    if (locationElement && locationElement.tagName === 'SELECT') {
        locationElement.addEventListener('change', (e) => {
            cartItems = [];
            renderCart();
            loadWasteTypes(e.target.value);
            loadProducts(e.target.value);
        });
    }

    if (wasteTypeSelect) {
        wasteTypeSelect.addEventListener('change', () => { /* validado al enviar */ });
    }

    if (productSelect) {
        productSelect.addEventListener('change', (e) => {
            const locId = currentLocationId();
            const prodId = parseInt(e.target.value);
            if (!isNaN(prodId) && locId) {
                loadLots(locId, prodId);
            }
        });
    }

    if (lotSelect) {
        lotSelect.addEventListener('change', updateQuantityConstraint);
    }

    // ====== SUBIDA DE FOTO (dropzone, opcional, subida automática) ======
    const resetPhotoDropzone = () => {
        dropzone.classList.remove('d-none');
        photoPreviewWrap.classList.add('d-none');
        if (photoPreview) photoPreview.removeAttribute('src');
        evidenceUrlInput.value = '';
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

    const handlePhotoFile = (file) => {
        if (!file) return;
        if (!file.type || !file.type.startsWith('image/')) {
            showAlert('warning', 'Solo se permiten archivos de imagen.');
            return;
        }

        // Mostrar vista previa inmediatamente
        dropzone.classList.add('d-none');
        photoPreviewWrap.classList.remove('d-none');
        photoPreview.src = URL.createObjectURL(file);
        photoState.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>Subiendo...';
        photoState.classList.remove('text-success');

        uploadPhoto(file);
    };

    const uploadPhoto = async (file) => {
        const formData = new FormData();
        formData.append('image', file);

        try {
            const response = await fetch('/api/waste/evidence', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (response.ok && result.success && result.url) {
                evidenceUrlInput.value = result.url;
                photoState.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i>Foto adjuntada';
                photoState.classList.add('text-success');
                showAlert('success', 'Foto de evidencia adjuntada correctamente.');
            } else {
                photoState.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>No se pudo subir';
                showAlert('warning', 'La foto no se pudo cargar, pero puede continuar sin ella.');
            }
        } catch (e) {
            photoState.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Error de conexión';
            showAlert('warning', 'Error al subir la foto; puede continuar sin ella.');
        }
    };

    if (btnRemovePhoto) {
        btnRemovePhoto.addEventListener('click', () => {
            resetPhotoDropzone();
            if (photoInput) photoInput.value = '';
        });
    }

    // ====== CARRITO ======
    const renderCart = () => {
        cartBody.innerHTML = '';
        if (cartItems.length === 0) {
            cartSection.classList.add('d-none');
            return;
        }
        cartSection.classList.remove('d-none');

        cartItems.forEach((item, index) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="fw-bold text-dark small">${item.product_name}</td>
                <td class="text-center text-danger fw-bold small">${item.quantity.toFixed(2)}</td>
                <td class="text-center small"><span class="badge bg-light text-dark border font-monospace">${item.lot_number}</span></td>
                <td class="text-center small text-muted">${item.expiration_date || '—'}</td>
                <td class="text-center">
                    <button type="button" class="btn btn-sm btn-outline-danger border-0" onclick="removeMermaItem(${index})">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            `;
            cartBody.appendChild(tr);
        });
    };

    window.removeMermaItem = (index) => {
        cartItems.splice(index, 1);
        renderCart();
    };

    btnAddToList.addEventListener('click', () => {
        alertContainer.innerHTML = '';

        const locId = currentLocationId();
        const wasteTypeId = +wasteTypeSelect.value;
        const productId = +productSelect.value;
        const productName = productSelect.options[productSelect.selectedIndex]?.text;
        const lotVal = lotSelect ? lotSelect.value : '';
        const qty = parseFloat(quantityInput.value);

        if (!locId) { showAlert('warning', 'Debe seleccionar una sede.'); return; }
        if (!wasteTypeId) { showAlert('warning', 'Debe seleccionar el tipo de merma.'); return; }
        if (isNaN(productId) || isNaN(qty) || qty <= 0) {
            showAlert('warning', 'Debe seleccionar un producto y una cantidad mayor a 0.');
            return;
        }
        if (!lotVal) {
            showAlert('warning', 'Debe seleccionar el lote específico del producto.');
            return;
        }

        const lotObj = currentLotsData.find(l => l.lot_number === lotVal);
        if (lotObj && lotObj.quantity != null && qty > parseFloat(lotObj.quantity)) {
            showAlert('warning', `El lote ${lotVal} solo dispone de ${lotObj.quantity} unidades.`);
            return;
        }

        cartItems.push({
            product_id: productId,
            product_name: productName,
            lot_number: lotVal,
            quantity: qty,
            expiration_date: (lotObj && lotObj.expiration_date) ? lotObj.expiration_date : '—'
        });

        productSelect.value = '';
        if (lotSelect) {
            lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
            lotSelect.disabled = true;
        }
        quantityInput.value = '';
        quantityInput.disabled = true;
        btnAddToList.disabled = true;
        renderCart();
    });

    // ====== ENVÍO ======
    btnSubmitMerma.addEventListener('click', async () => {
        if (cartItems.length === 0) return;

        const locId = currentLocationId();
        const wasteTypeId = +wasteTypeSelect.value;
        const notes = notesInput.value.trim();

        if (!wasteTypeId) { showAlert('warning', 'Debe seleccionar el tipo de merma.'); return; }
        if (!notes) { showAlert('warning', 'El motivo de la merma es obligatorio.'); return; }

        const originalHtml = btnSubmitMerma.innerHTML;
        btnSubmitMerma.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Procesando...';
        btnSubmitMerma.disabled = true;

        const payload = {
            location_id: parseInt(locId),
            waste_type_id: wasteTypeId,
            notes: notes,
            evidence_url: evidenceUrlInput.value || null,
            items: cartItems.map(item => ({
                product_id: item.product_id,
                lot_number: item.lot_number,
                quantity: item.quantity
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
                renderCart();
                notesInput.value = '';
                evidenceUrlInput.value = '';
                if (typeof resetPhotoDropzone === 'function') resetPhotoDropzone();
                if (photoInput) photoInput.value = '';

                showAlert('success', result.message);
                if (locationElement && locationElement.tagName === 'SELECT') {
                    loadProducts(locationElement.value);
                    loadWasteTypes(locationElement.value);
                } else {
                    await loadProducts(currentLocationId());
                    await loadWasteTypes(currentLocationId());
                }
            } else {
                let errorText = result.message || 'Error al registrar la merma.';
                if (result.errors) {
                    errorText = Object.entries(result.errors).map(([k, v]) => `${v}`).join(' · ');
                }
                showAlert('danger', errorText);
            }
        } catch (e) {
            showAlert('danger', 'Error de conexión con el servidor.');
        } finally {
            btnSubmitMerma.innerHTML = originalHtml;
            btnSubmitMerma.disabled = false;
        }
    });
});
