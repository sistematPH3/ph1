// =========================================================================
// SECCIÓN 1: FORMULARIO DE DESPACHO E INSUMOS
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
    const itemsBody = document.getElementById('itemsBody');
    const btnAddRow = document.getElementById('btnAddRow');
    const dispatchForm = document.getElementById('dispatchForm');
    const productOptionsTemplateEl = document.getElementById('productOptionsTemplate');

    // Obtener fecha actual en formato AAAA-MM-DD para bloquear el calendario
    const todayStr = new Date().toISOString().split('T')[0];

    if (!dispatchForm || !itemsBody || !productOptionsTemplateEl) return;

    const productOptionsTemplate = productOptionsTemplateEl.innerHTML;

    // Helper para leer el ID del origen sin importar si el select está deshabilitado por ROL
    function getOriginLocationId() {
        const originSelect = document.getElementById('origin_location_id');
        if (originSelect && originSelect.disabled) {
            return document.getElementById('origin_location_id_hidden')?.value || originSelect.value;
        }
        return originSelect ? originSelect.value : '';
    }

    // Helper para leer el ID del destino sin importar si está deshabilitado por ROL
    function getDestinationLocationId() {
        const destSelect = document.getElementById('destination_location_id');
        if (destSelect && destSelect.disabled) {
            return document.getElementById('destination_location_id_hidden')?.value || destSelect.value;
        }
        return destSelect ? destSelect.value : '';
    }

    // Validar en tiempo real que Origen y Destino no sean la misma sede y marcar visualmente
function validateLocations() {
    const originSelect = document.getElementById('origin_location_id');
    const destSelect = document.getElementById('destination_location_id');
    const destFeedback = document.getElementById('destinationFeedback');
    const originId = getOriginLocationId();

    // Marcar origen como válido si tiene valor y no está deshabilitado
    if (originSelect && !originSelect.disabled) {
        if (originId) {
            originSelect.classList.remove('is-invalid');
            originSelect.classList.add('is-valid');
        } else {
            originSelect.classList.remove('is-valid', 'is-invalid');
        }
    }

    if (!destSelect) return true;

    const destId = destSelect.value;

    if (originId && destId && originId === destId) {
        destSelect.classList.remove('is-valid');
        destSelect.classList.add('is-invalid');
        if (destFeedback) {
            destFeedback.textContent = 'La sede de destino no puede ser igual a la sede de origen.';
        }
        return false;
    } else if (destId) {
        destSelect.classList.remove('is-invalid');
        
        // Solo mostrar la tilde verde si el campo está activo/editable
        if (!destSelect.disabled) {
            destSelect.classList.add('is-valid');
        } else {
            destSelect.classList.remove('is-valid');
        }

        if (destFeedback) {
            destFeedback.textContent = 'Por favor, seleccione la sede de destino.';
        }
        return true;
    }
    return false;
}

    // Escuchar cambios de sedes
    document.getElementById('origin_location_id')?.addEventListener('change', validateLocations);
    document.getElementById('destination_location_id')?.addEventListener('change', validateLocations);

    // Consultar la base de datos para verificar si el producto está en 0 unidades
    async function checkStockForRow(row) {
        const productSelect = row.querySelector('.product-select');
        const qtyInput = row.querySelector('.quantity-input');
        const qtyFeedback = qtyInput ? qtyInput.nextElementSibling : null;
        
        const originId = getOriginLocationId();
        const productId = productSelect.value;

        if (!originId || !productId) return;

        try {
            const response = await fetch(`/logistics/movements/check-stock?location_id=${originId}&product_id=${productId}`);
            const data = await response.json();

            if (data.success) {
                const availableStock = data.stock;
                row.dataset.availableStock = availableStock;

                // El producto fue seleccionado correctamente: se asegura estado válido en el select
                productSelect.classList.remove('is-invalid');
                productSelect.classList.add('is-valid');

                if (availableStock <= 0) {
                    qtyInput.classList.remove('is-valid');
                    qtyInput.classList.add('is-invalid');
                    if (qtyFeedback) {
                        qtyFeedback.textContent = 'Este producto no existe o se encuentra en 0 unidades.';
                    }
                } else {
                    validateQuantityInput(row);
                }
            }
        } catch (err) {
            console.error('Error al verificar stock:', err);
        }
    }

    // Validar que la cantidad ingresada sea mayor a 0 y no supere el disponible
    function validateQuantityInput(row) {
        const qtyInput = row.querySelector('.quantity-input');
        const qtyFeedback = qtyInput ? qtyInput.nextElementSibling : null;
        const availableStock = parseFloat(row.dataset.availableStock || 0);
        const enteredQty = parseFloat(qtyInput.value) || 0;

        if (enteredQty <= 0) {
            qtyInput.classList.remove('is-valid');
            qtyInput.classList.add('is-invalid');
            if (qtyFeedback) qtyFeedback.textContent = 'La cantidad debe ser mayor a 0.';
        } else if (row.dataset.availableStock !== undefined && enteredQty > availableStock) {
            qtyInput.classList.remove('is-valid');
            qtyInput.classList.add('is-invalid');
            if (qtyFeedback) qtyFeedback.textContent = `Stock insuficiente. Disponible: ${availableStock}`;
        } else {
            qtyInput.classList.remove('is-invalid');
            qtyInput.classList.add('is-valid');
        }
    }

    // Función para añadir filas con las nuevas restricciones y validaciones en tiempo real
    function addRow() {
        const rowId = Date.now();
        const tr = document.createElement('tr');
        tr.id = `row-${rowId}`;
        
        tr.innerHTML = `
            <td>
                <select class="form-select ph-pill-input product-select" required>
                    ${productOptionsTemplate}
                </select>
                <div class="invalid-feedback ps-2">Seleccione un producto.</div>
            </td>
            <td>
                <input type="number" step="0.01" min="0.01" class="form-control ph-pill-input quantity-input" placeholder="0.00" required>
                <div class="invalid-feedback ps-2">La cantidad debe ser mayor a 0.</div>
            </td>
            <td>
                <input type="text" class="form-control ph-pill-input lot-input" placeholder="N° de Lote" required>
                <div class="invalid-feedback ps-2">El lote es obligatorio.</div>
            </td>
            <td>
                <input type="date" min="${todayStr}" class="form-control ph-pill-input exp-input" required>
                <div class="invalid-feedback ps-2">La fecha de vencimiento es obligatoria y no puede ser pasada.</div>
            </td>
            <td class="text-center">
                <button type="button" class="btn btn-ph-delete btn-sm btn-delete shadow-sm" title="Eliminar fila">
                    <i class="bi bi-trash-fill"></i>
                </button>
            </td>
        `;

        const productSelect = tr.querySelector('.product-select');
        const qtyInput = tr.querySelector('.quantity-input');
        const lotInput = tr.querySelector('.lot-input');
        const expInput = tr.querySelector('.exp-input');

        productSelect.addEventListener('change', () => checkStockForRow(tr));
        qtyInput.addEventListener('input', () => validateQuantityInput(tr));

        // Validación en tiempo real para N° de Lote
        lotInput.addEventListener('input', () => {
            if (lotInput.value.trim() !== '') {
                lotInput.classList.remove('is-invalid');
                lotInput.classList.add('is-valid');
            } else {
                lotInput.classList.remove('is-valid');
            }
        });

        // Validación en tiempo real para Fecha de Vencimiento
        const validateExp = () => {
            if (expInput.value && expInput.value >= todayStr) {
                expInput.classList.remove('is-invalid');
                expInput.classList.add('is-valid');
            } else if (expInput.value) {
                expInput.classList.remove('is-valid');
                expInput.classList.add('is-invalid');
            } else {
                expInput.classList.remove('is-valid');
            }
        };

        expInput.addEventListener('change', validateExp);
        expInput.addEventListener('input', validateExp);

        tr.querySelector('.btn-delete').addEventListener('click', () => {
            tr.remove();
        });

        itemsBody.appendChild(tr);
    }

    // Agregar primera fila por defecto
    addRow();

    if (btnAddRow) {
        btnAddRow.addEventListener('click', addRow);
    }

    // Ejecutar validación inicial al cargar las sedes
    validateLocations();

    // Envío del formulario asíncrono
    dispatchForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        dispatchForm.classList.add('was-validated');

        if (!validateLocations()) {
            document.getElementById('destination_location_id')?.focus();
            return;
        }

        const rows = itemsBody.querySelectorAll('tr');
        if (rows.length === 0) {
            alert('Debe agregar al menos un producto a la lista de despacho.');
            return;
        }

        let formIsValid = true;
        rows.forEach(row => {
            const qtyInput = row.querySelector('.quantity-input');
            const productSelect = row.querySelector('.product-select');
            const lotInput = row.querySelector('.lot-input');
            const expInput = row.querySelector('.exp-input');

            if (qtyInput?.classList.contains('is-invalid') || 
                productSelect?.classList.contains('is-invalid') ||
                lotInput?.classList.contains('is-invalid') ||
                expInput?.classList.contains('is-invalid')) {
                formIsValid = false;
            }
        });

        if (!formIsValid || !dispatchForm.checkValidity()) {
            const firstInvalid = dispatchForm.querySelector('.is-invalid, :invalid');
            if (firstInvalid) firstInvalid.focus();
            return;
        }

        const items = [];
        rows.forEach(row => {
            const productId = row.querySelector('.product-select').value;
            const quantity = row.querySelector('.quantity-input').value;
            const lotNumber = row.querySelector('.lot-input').value;
            const expirationDate = row.querySelector('.exp-input').value;

            items.push({
                product_id: parseInt(productId),
                quantity: parseFloat(quantity),
                lot_number: lotNumber.trim(),
                expiration_date: expirationDate ? expirationDate : null
            });
        });

        const payload = {
            origin_location_id: parseInt(getOriginLocationId()),
            destination_location_id: parseInt(getDestinationLocationId()),
            items: items
        };

        try {
            const response = await fetch('/logistics/movements/dispatch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok && result.success) {
                const successModalEl = document.getElementById('successModal');
                const modalMessage = document.getElementById('successModalMessage');
                const btnSuccessOk = document.getElementById('btnSuccessOk');

                if (modalMessage) {
                    modalMessage.textContent = result.message || 'El despacho se ha emitido exitosamente.';
                }

                const modalInstance = new bootstrap.Modal(successModalEl);
                modalInstance.show();

                if (btnSuccessOk) {
                    btnSuccessOk.addEventListener('click', () => {
                        window.location.href = '/logistics/movements';
                    });
                }
            } else {
                const errorMsg = result.errors ? result.errors.join('\n') : 'Ocurrió un error inesperado.';
                alert(`Error al procesar despacho:\n${errorMsg}`);
            }
        } catch (error) {
            console.error('Error en la petición:', error);
            alert('Error de conexión con el servidor.');
        }
    });
});

// =========================================================================
// SECCIÓN 2: LÓGICA DE CANCELACIÓN DE SALIDA
// =========================================================================
window.cancelarSalida = function(movementId) {
    const cancelInput = document.getElementById('cancelMovementId');
    const reasonInput = document.getElementById('cancelReason');
    const modalEl = document.getElementById('cancelModal');
    
    if (cancelInput && reasonInput && modalEl) {
        cancelInput.value = movementId;
        reasonInput.value = '';
        const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        modalInstance.show();
    }
};

document.addEventListener('DOMContentLoaded', () => {
    const btnConfirmCancel = document.getElementById('btnConfirmCancel');
    
    if (btnConfirmCancel) {
        btnConfirmCancel.addEventListener('click', async () => {
            const movementId = document.getElementById('cancelMovementId').value;
            const reasonInput = document.getElementById('cancelReason');
            const reason = reasonInput.value.trim();
            const alertDiv = document.getElementById('cancelModalAlert');

            if (alertDiv) alertDiv.className = 'alert py-2 small mb-3 d-none';

            if (!reason) {
                if (alertDiv) {
                    alertDiv.className = 'alert alert-danger py-2 small mb-3';
                    alertDiv.textContent = 'Por favor, ingrese el motivo de la cancelación.';
                }
                reasonInput.focus();
                return;
            }

            try {
                const response = await fetch(`/logistics/movements/cancel-dispatch/${movementId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason })
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    if (alertDiv) {
                        alertDiv.className = 'alert alert-success py-2 small mb-3';
                        alertDiv.textContent = result.message || '¡Traslado cancelado y stock revertido con éxito!';
                    }
                    btnConfirmCancel.disabled = true;
                    setTimeout(() => { window.location.reload(); }, 1500);
                } else {
                    const errorMsg = result.errors ? result.errors.join('\n') : (result.message || 'Error al cancelar.');
                    if (alertDiv) {
                        alertDiv.className = 'alert alert-danger py-2 small mb-3';
                        alertDiv.textContent = errorMsg;
                    }
                }
            } catch (error) {
                console.error('Error al procesar la cancelación:', error);
                if (alertDiv) {
                    alertDiv.className = 'alert alert-danger py-2 small mb-3';
                    alertDiv.textContent = 'Error de conexión con el servidor.';
                }
            }
        });
    }
});