document.addEventListener('DOMContentLoaded', () => {
    const locationElement = document.getElementById('location_id');
    const productSelect = document.getElementById('product_id');
    const consumptionForm = document.getElementById('consumptionForm');
    const btnSubmit = document.getElementById('btnSubmitConsumption');
    const alertContainer = document.getElementById('alertContainer');

    const loadProducts = async (locationId) => {
        productSelect.innerHTML = '<option value="" selected disabled>Buscando inventario...</option>';
        productSelect.disabled = true;
        btnSubmit.disabled = true;
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
                    btnSubmit.disabled = false;
                }
            }
        } catch (error) {
            productSelect.innerHTML = '<option value="" selected disabled>Error de conexión</option>';
        }
    };

    if (locationElement && locationElement.value) {
        loadProducts(locationElement.value);
    }

    if (locationElement && locationElement.tagName === 'SELECT') {
        locationElement.addEventListener('change', (e) => {
            loadProducts(e.target.value);
        });
    }

    consumptionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const originalBtnHtml = btnSubmit.innerHTML;
        btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Procesando...';
        btnSubmit.disabled = true;
        alertContainer.innerHTML = '';

        const payload = {
            location_id: parseInt(locationElement.value),
            product_id: parseInt(productSelect.value),
            quantity: parseFloat(document.getElementById('quantity').value),
            notes: document.getElementById('notes').value || ""
        };

        if (isNaN(payload.product_id)) {
            alertContainer.innerHTML = `
                <div class="alert alert-warning alert-dismissible fade show shadow-sm" role="alert">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i> Debes seleccionar un producto válido.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            btnSubmit.innerHTML = originalBtnHtml;
            btnSubmit.disabled = false;
            return;
        }

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
                alertContainer.innerHTML = `
                    <div class="alert alert-success alert-dismissible fade show shadow-sm" role="alert">
                        <i class="bi bi-check-circle-fill me-2"></i> ${result.message}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
                
                document.getElementById('quantity').value = '';
                document.getElementById('notes').value = '';
                
                await loadProducts(locationElement.value);
            } else {
                let errorText = result.message || 'Error al registrar el consumo.';
                if (result.errors) {
                    errorText = Object.entries(result.errors).map(([k, v]) => `<strong>${k}</strong>: ${v}`).join('<br>');
                }
                
                alertContainer.innerHTML = `
                    <div class="alert alert-danger alert-dismissible fade show shadow-sm" role="alert">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i> ${errorText}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                    </div>
                `;
                btnSubmit.disabled = false;
            }
        } catch (error) {
            alertContainer.innerHTML = `
                <div class="alert alert-danger alert-dismissible fade show shadow-sm" role="alert">
                    <i class="bi bi-wifi-off me-2"></i> Error crítico: No se pudo conectar con el servidor.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            btnSubmit.disabled = false;
        } finally {
            btnSubmit.innerHTML = originalBtnHtml;
        }
    });
});