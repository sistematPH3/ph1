document.addEventListener('DOMContentLoaded', () => {
    const locationElement = document.getElementById('location_id');
    const productSelect = document.getElementById('product_id');
    const lotSelect = document.getElementById('lot_number');
    const inputQuantity = document.getElementById('quantity');
    const inputNotes = document.getElementById('notes');
    const alertContainer = document.getElementById('alertContainer');
    const btnAddToList = document.getElementById('btnAddToList');
    const cartSection = document.getElementById('cartSection');
    const cartBody = document.getElementById('cartBody');
    const btnSubmitBatch = document.getElementById('btnSubmitBatch');

    let cartItems = [];
    let currentLotsData = [];

    const lotStatusText = document.getElementById('lotStatusText');

    const getAutoLotBreakdown = (qty) => {
        const breakdown = [];
        let remaining = qty;
        for (const lot of currentLotsData) {
            if (remaining <= 0) break;
            const useFromLot = Math.min(remaining, parseFloat(lot.quantity));
            if (useFromLot > 0) {
                breakdown.push({ lot_number: lot.lot_number, qty: useFromLot });
                remaining -= useFromLot;
            }
        }
        if (remaining > 0.001) {
            breakdown.push({ lot_number: 'S/L (General)', qty: remaining });
        }
        return breakdown;
    };

    const formatBreakdown = (breakdown) => {
        if (breakdown.length === 0) return 'General (sin lote)';
        const parts = breakdown.map(b => `${b.lot_number} (${b.qty.toFixed(2)})`);
        if (parts.length <= 2) return parts.join(' · ');
        return `${parts[0]} · … · ${parts[parts.length - 1]}`;
    };

    const updateLotStatus = () => {
        if (!lotStatusText) return;
        if (!lotSelect || !productSelect || !productSelect.value) {
            lotStatusText.textContent = 'Seleccione un producto';
            return;
        }
        const selectedVal = lotSelect.value;
        if (selectedVal) {
            lotStatusText.textContent = `Lote: ${selectedVal}`;
        } else if (currentLotsData.length > 1) {
            const qtyVal = parseFloat(inputQuantity.value);
            if (!isNaN(qtyVal) && qtyVal > 0) {
                lotStatusText.textContent = `Auto: ${formatBreakdown(getAutoLotBreakdown(qtyVal))}`;
            } else {
                lotStatusText.textContent = `Auto (1º: ${currentLotsData[0].lot_number})`;
            }
        } else if (currentLotsData.length === 1) {
            lotStatusText.textContent = `Lote: ${currentLotsData[0].lot_number}`;
        } else {
            lotStatusText.textContent = 'General (sin lote)';
        }
    };

    const updateQuantityConstraint = () => {
        if (!lotSelect || !inputQuantity) return;
        
        const selectedLotVal = lotSelect.value;
        if (!selectedLotVal) {
            inputQuantity.removeAttribute('max');
            inputQuantity.setAttribute('placeholder', '0.00 (Total turno)');
            return;
        }

        const lotObj = currentLotsData.find(l => l.lot_number === selectedLotVal);
        if (lotObj && lotObj.quantity != null) {
            const maxQty = parseFloat(lotObj.quantity);
            inputQuantity.setAttribute('max', maxQty.toFixed(2));
            inputQuantity.setAttribute('placeholder', `Máx: ${maxQty.toFixed(2)}`);
            
            const currentVal = parseFloat(inputQuantity.value);
            if (!isNaN(currentVal) && currentVal > maxQty) {
                inputQuantity.value = maxQty.toFixed(2);
            }
        } else {
            inputQuantity.removeAttribute('max');
            inputQuantity.setAttribute('placeholder', '0.00');
        }
    };

    const loadLots = async (locationId, productId) => {
        if (!lotSelect) return;

        lotSelect.innerHTML = '<option value="" selected disabled>Cargando lotes...</option>';
        lotSelect.disabled = true;
        currentLotsData = [];

        try {
            const response = await fetch(`/api/inventory/locations/${locationId}/products/${productId}/lots`);
            const result = await response.json();

            if (response.ok && result.success) {
                lotSelect.innerHTML = '';
                currentLotsData = Array.isArray(result.lots) ? result.lots : [];

                if (currentLotsData.length === 0) {
                    const defaultOption = document.createElement('option');
                    defaultOption.value = '';
                    defaultOption.textContent = 'Sin lotes específicos (General)';
                    defaultOption.selected = true;
                    lotSelect.appendChild(defaultOption);
                } else if (currentLotsData.length === 1) {
                    const onlyLot = currentLotsData[0];
                    const onlyOption = document.createElement('option');
                    onlyOption.value = onlyLot.lot_number;
                    onlyOption.textContent = `${onlyLot.lot_number} (Vence: ${onlyLot.expiration_date} | Disp: ${onlyLot.quantity})`;
                    onlyOption.dataset.maxQuantity = onlyLot.quantity;
                    onlyOption.selected = true;
                    lotSelect.appendChild(onlyOption);
                } else {
                    const autoOption = document.createElement('option');
                    autoOption.value = '';
                    autoOption.textContent = `⚡ Automático (1º: ${currentLotsData[0].lot_number})`;
                    autoOption.selected = true;
                    lotSelect.appendChild(autoOption);

                    currentLotsData.forEach((lot) => {
                        const option = document.createElement('option');
                        option.value = lot.lot_number;
                        option.textContent = `${lot.lot_number} (Vence: ${lot.expiration_date} | Disp: ${lot.quantity})`;
                        option.dataset.maxQuantity = lot.quantity;
                        lotSelect.appendChild(option);
                    });
                }
                lotSelect.disabled = false;
                updateQuantityConstraint();
                updateLotStatus();
            }
        } catch (error) {
            lotSelect.innerHTML = '<option value="" selected disabled>Error al cargar lotes</option>';
        }
    };

    const loadProducts = async (locationId) => {
        productSelect.innerHTML = '<option value="" selected disabled>Buscando inventario...</option>';
        productSelect.disabled = true;
        if (lotSelect) {
            lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
            lotSelect.disabled = true;
        }
        if (lotStatusText) lotStatusText.textContent = 'Seleccione un producto';
        btnAddToList.disabled = true;
        alertContainer.innerHTML = '';
        inputQuantity.value = '';
        inputQuantity.removeAttribute('max');
        inputQuantity.setAttribute('placeholder', '0.00');

        try {
            const response = await fetch(`/api/inventory/locations/${locationId}/products`);
            const result = await response.json();

            if (response.ok && result.success) {
                productSelect.innerHTML = '<option value="" selected disabled>Seleccione un producto...</option>';
                
                if (result.products.length === 0) {
                    productSelect.innerHTML = '<option value="" selected disabled>Sin inventario registrado en esta sede</option>';
                    alertContainer.innerHTML = `
                        <div class="alert alert-warning alert-dismissible fade show shadow-sm" role="alert">
                            <i class="bi bi-info-circle-fill me-2"></i> No se puede realizar un consumo al no tener nada en el inventario de la sede.
                            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                        </div>
                    `;
                } else {
                    result.products.forEach(product => {
                        const option = document.createElement('option');
                        option.value = product.id;
                        option.textContent = product.name;
                        productSelect.appendChild(option);
                    });
                    productSelect.disabled = false;
                    btnAddToList.disabled = false;
                }
            }
        } catch (error) {
            productSelect.innerHTML = '<option value="" selected disabled>Error de conexión</option>';
        }
    };

    const renderCart = () => {
        cartBody.innerHTML = '';
        
        if (cartItems.length === 0) {
            cartSection.classList.add('d-none');
            if (locationElement.tagName === 'SELECT') {
                locationElement.disabled = false;
            }
            return;
        }

        cartSection.classList.remove('d-none');
        if (locationElement.tagName === 'SELECT') {
            locationElement.disabled = true;
        }

        cartItems.forEach((item, index) => {
            const tr = document.createElement('tr');
            let displayLot = item.lot_number || 'S/L (General)';
            if (item.auto_breakdown && item.auto_breakdown.length) {
                displayLot = item.auto_breakdown.map(b => `${b.lot_number} (${b.qty.toFixed(2)})`).join(' · ');
            } else if (!item.lot_number && item.nearest_lot) {
                displayLot = `⚡ ${item.nearest_lot}`;
            }
            tr.innerHTML = `
                <td class="fw-bold text-dark small">${item.product_name}</td>
                <td class="text-center text-danger fw-bold small">${item.quantity.toFixed(2)}</td>
                <td class="text-center small"><span class="badge bg-light text-dark border font-monospace">${displayLot}</span></td>
                <td class="small text-muted">${item.notes || '-'}</td>
                <td class="text-center">
                    <button type="button" class="btn btn-sm btn-outline-danger border-0" onclick="removeItem(${index})">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            `;
            cartBody.appendChild(tr);
        });
    };

    window.removeItem = (index) => {
        cartItems.splice(index, 1);
        renderCart();
    };

    if (locationElement && locationElement.value) {
        loadProducts(locationElement.value);
    }

    if (locationElement && locationElement.tagName === 'SELECT') {
        locationElement.addEventListener('change', (e) => {
            cartItems = [];
            renderCart();
            loadProducts(e.target.value);
        });
    }

    productSelect.addEventListener('change', (e) => {
        const prodId = parseInt(e.target.value);
        const locId = parseInt(locationElement.value);
        if (!isNaN(prodId) && !isNaN(locId)) {
            loadLots(locId, prodId);
        }
    });

    if (lotSelect) {
        lotSelect.addEventListener('change', () => {
            updateQuantityConstraint();
            updateLotStatus();
        });
    }

    inputQuantity.addEventListener('input', () => {
        if (inputQuantity.value.length > 8) {
            inputQuantity.value = inputQuantity.value.slice(0, 8);
        }

        const selectedLotVal = lotSelect ? lotSelect.value : '';
        if (selectedLotVal) {
            const lotObj = currentLotsData.find(l => l.lot_number === selectedLotVal);
            if (lotObj && lotObj.quantity != null) {
                const maxQty = parseFloat(lotObj.quantity);
                const currentVal = parseFloat(inputQuantity.value);
                if (!isNaN(currentVal) && currentVal > maxQty) {
                    inputQuantity.value = maxQty.toFixed(2);
                }
            }
        }
        updateLotStatus();
    });

    btnAddToList.addEventListener('click', () => {
        alertContainer.innerHTML = '';
        
        const productId = parseInt(productSelect.value);
        const productName = productSelect.options[productSelect.selectedIndex]?.text;
        const lotVal = lotSelect ? lotSelect.value : '';
        const qty = parseFloat(inputQuantity.value);
        const notes = inputNotes.value.trim();

        if (isNaN(productId) || isNaN(qty) || qty <= 0) {
            alertContainer.innerHTML = `
                <div class="alert alert-warning alert-dismissible fade show shadow-sm" role="alert">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i> Debes seleccionar un producto y una cantidad válida mayor a 0.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            return;
        }

        if (lotVal) {
            const lotObj = currentLotsData.find(l => l.lot_number === lotVal);
            if (lotObj && lotObj.quantity != null) {
                const maxQty = parseFloat(lotObj.quantity);
                if (qty > maxQty) {
                    alertContainer.innerHTML = `
                        <div class="alert alert-warning alert-dismissible fade show shadow-sm" role="alert">
                            <i class="bi bi-exclamation-circle-fill me-2"></i> El lote seleccionado solo cuenta con ${maxQty.toFixed(2)} unidades. Para consumos mayores use la opción automática.
                            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                        </div>
                    `;
                    return;
                }
            }
        }

        const existingIndex = cartItems.findIndex(i => i.product_id === productId && i.lot_number === lotVal);
        if (existingIndex > -1) {
            const newTotalQty = cartItems[existingIndex].quantity + qty;
            if (lotVal) {
                const lotObj = currentLotsData.find(l => l.lot_number === lotVal);
                if (lotObj && newTotalQty > parseFloat(lotObj.quantity)) {
                    alertContainer.innerHTML = `
                        <div class="alert alert-warning alert-dismissible fade show shadow-sm" role="alert">
                            <i class="bi bi-exclamation-circle-fill me-2"></i> La suma de este lote en la lista superaría las ${parseFloat(lotObj.quantity).toFixed(2)} unidades disponibles.
                            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                        </div>
                    `;
                    return;
                }
            }
            cartItems[existingIndex].quantity = newTotalQty;
            if (!lotVal) {
                cartItems[existingIndex].auto_breakdown = getAutoLotBreakdown(newTotalQty);
            }
            if (notes) cartItems[existingIndex].notes = cartItems[existingIndex].notes + " | " + notes;
        } else {
            const nearest_lot = (!lotVal && currentLotsData.length > 0) ? currentLotsData[0].lot_number : null;
            const auto_breakdown = (!lotVal && currentLotsData.length > 0) ? getAutoLotBreakdown(qty) : [];
            cartItems.push({
                product_id: productId,
                product_name: productName,
                lot_number: lotVal,
                nearest_lot: nearest_lot,
                auto_breakdown: auto_breakdown,
                quantity: qty,
                notes: notes
            });
        }

        productSelect.value = '';
        if (lotSelect) {
            lotSelect.innerHTML = '<option value="" selected disabled>Esperando producto...</option>';
            lotSelect.disabled = true;
        }
        inputQuantity.value = '';
        inputQuantity.removeAttribute('max');
        inputQuantity.setAttribute('placeholder', '0.00');
        inputNotes.value = '';
        updateLotStatus();
        renderCart();
    });

    btnSubmitBatch.addEventListener('click', async () => {
        if (cartItems.length === 0) return;

        const originalBtnHtml = btnSubmitBatch.innerHTML;
        btnSubmitBatch.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Procesando Lote...';
        btnSubmitBatch.disabled = true;
        alertContainer.innerHTML = '';

        const payload = {
            location_id: parseInt(locationElement.value),
            items: cartItems.map(item => ({
                product_id: item.product_id,
                lot_number: item.lot_number,
                quantity: item.quantity,
                notes: item.notes
            }))
        };

        try {
            const response = await fetch('/api/inventory/register-consumption', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok) {
                cartItems = [];
                renderCart();
                await loadProducts(locationElement.value);
                
                alertContainer.innerHTML = `
                    <div class="alert alert-success alert-dismissible fade show shadow-sm" role="alert">
                        <i class="bi bi-check-circle-fill me-2"></i> ${result.message}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
            } else {
                let errorText = result.message || 'Error al procesar el lote.';
                if (result.errors) {
                    errorText = Object.entries(result.errors).map(([k, v]) => `<strong>${k}</strong>: ${v}`).join('<br>');
                }
                
                alertContainer.innerHTML = `
                    <div class="alert alert-danger alert-dismissible fade show shadow-sm" role="alert">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i> ${errorText}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
            }
        } catch (error) {
            alertContainer.innerHTML = `
                <div class="alert alert-danger alert-dismissible fade show shadow-sm" role="alert">
                    <i class="bi bi-wifi-off me-2"></i> Error crítico: No se pudo conectar con el servidor.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
        } finally {
            btnSubmitBatch.innerHTML = originalBtnHtml;
            btnSubmitBatch.disabled = false;
        }
    });
});