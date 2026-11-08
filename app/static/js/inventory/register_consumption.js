document.addEventListener('DOMContentLoaded', () => {
    const locationElement = document.getElementById('location_id');
    const productSelect = document.getElementById('product_id');
    const inputQuantity = document.getElementById('quantity');
    const inputNotes = document.getElementById('notes');
    const alertContainer = document.getElementById('alertContainer');
    const btnAddToList = document.getElementById('btnAddToList');
    const cartSection = document.getElementById('cartSection');
    const cartBody = document.getElementById('cartBody');
    const btnSubmitBatch = document.getElementById('btnSubmitBatch');

    let cartItems = [];

    const loadProducts = async (locationId) => {
        productSelect.innerHTML = '<option value="" selected disabled>Buscando inventario...</option>';
        productSelect.disabled = true;
        btnAddToList.disabled = true;
        alertContainer.innerHTML = '';

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
            tr.innerHTML = `
                <td class="fw-bold text-dark small">${item.product_name}</td>
                <td class="text-center text-danger fw-bold small">${item.quantity.toFixed(2)}</td>
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

    btnAddToList.addEventListener('click', () => {
        alertContainer.innerHTML = '';
        
        const productId = parseInt(productSelect.value);
        const productName = productSelect.options[productSelect.selectedIndex]?.text;
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

        const existingIndex = cartItems.findIndex(i => i.product_id === productId);
        if (existingIndex > -1) {
            cartItems[existingIndex].quantity += qty;
            if (notes) cartItems[existingIndex].notes = cartItems[existingIndex].notes + " | " + notes;
        } else {
            cartItems.push({
                product_id: productId,
                product_name: productName,
                quantity: qty,
                notes: notes
            });
        }

        productSelect.value = '';
        inputQuantity.value = '';
        inputNotes.value = '';
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