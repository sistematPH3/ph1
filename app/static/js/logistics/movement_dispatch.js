// ==========================================
// LÓGICA DE CREACIÓN DE DESPACHO (Formulario)
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    const itemsBody = document.getElementById('itemsBody');
    const btnAddRow = document.getElementById('btnAddRow');
    const dispatchForm = document.getElementById('dispatchForm');
    const productOptionsTemplateEl = document.getElementById('productOptionsTemplate');

    if (dispatchForm && itemsBody && productOptionsTemplateEl) {
        const productOptionsTemplate = productOptionsTemplateEl.innerHTML;

        // Función para aplicar clases de validación en tiempo real a una entrada
        function setupRealtimeValidation(inputEl) {
            const eventType = inputEl.tagName === 'SELECT' ? 'change' : 'input';
            
            inputEl.addEventListener(eventType, () => {
                if (inputEl.checkValidity()) {
                    inputEl.classList.remove('is-invalid');
                    inputEl.classList.add('is-valid');
                } else {
                    inputEl.classList.remove('is-valid');
                    inputEl.classList.add('is-invalid');
                }
            });
        }

        // Agregar validación en tiempo real a los campos estáticos
        document.querySelectorAll('#origin_location_id, #destination_location_id').forEach(select => {
            setupRealtimeValidation(select);
        });

        // Función para añadir filas a la tabla
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
                    <div class="invalid-feedback ps-2">La cantidad debe ser mayor a 0 </div>
                </td>
                <td>
                    <input type="text" class="form-control ph-pill-input lot-input" placeholder="N° de Lote" required>
                    <div class="invalid-feedback ps-2">El lote es obligatorio.</div>
                </td>
                <td>
                    <input type="date" class="form-control ph-pill-input exp-input" required>
                    <div class="invalid-feedback ps-2">La fecha es obligatoria.</div>
                </td>
                <td class="text-center">
                    <button type="button" class="btn btn-ph-delete btn-sm btn-delete shadow-sm" title="Eliminar fila">
                        <i class="bi bi-trash-fill"></i>
                    </button>
                </td>
            `;

            // Escuchar cambios en los inputs de la nueva fila para validación instantánea
            tr.querySelectorAll('.form-select, .form-control').forEach(input => {
                setupRealtimeValidation(input);
            });

            // Acción del botón Eliminar
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

        // Envío del formulario asíncrono
        dispatchForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            // 1. Activar marcado visual de validación general
            dispatchForm.classList.add('was-validated');

            // Validar si la tabla tiene al menos una fila
            const rows = itemsBody.querySelectorAll('tr');
            if (rows.length === 0) {
                alert('Debe agregar al menos un producto a la lista de despacho.');
                return;
            }

            // Validar que todos los campos del formulario cumplan con las reglas (required, min, etc.)
            let formIsValid = true;
            const inputs = dispatchForm.querySelectorAll('select[required], input[required]');
            
            inputs.forEach(input => {
                if (!input.checkValidity()) {
                    input.classList.add('is-invalid');
                    formIsValid = false;
                }
            });

            // Validar que las sedes origen y destino no sean la misma
            const originId = document.getElementById('origin_location_id').value;
            const destinationId = document.getElementById('destination_location_id').value;

            if (originId && destinationId && originId === destinationId) {
                const destSelect = document.getElementById('destination_location_id');
                destSelect.classList.add('is-invalid');
                alert('La sede de origen y la sede de destino no pueden ser iguales.');
                return;
            }

            if (!formIsValid || !dispatchForm.checkValidity()) {
                // Desplazar la vista al primer elemento con error
                const firstInvalid = dispatchForm.querySelector('.is-invalid, :invalid');
                if (firstInvalid) firstInvalid.focus();
                return;
            }

            // 2. Construir el Payload
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
                origin_location_id: parseInt(originId),
                destination_location_id: parseInt(destinationId),
                items: items
            };

            // 3. Enviar datos al backend
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

                    btnSuccessOk.addEventListener('click', () => {
                        window.location.href = '/logistics/movements';
                    });
                } else {
                    const errorMsg = result.errors ? result.errors.join('\n') : 'Ocurrió un error inesperado.';
                    alert(`Error al procesar despacho:\n${errorMsg}`);
                }
            } catch (error) {
                console.error('Error en la petición:', error);
                alert('Error de conexión con el servidor.');
            }
        });
    }
});

// ==========================================
// LÓGICA DE CANCELACIÓN DE SALIDA (Modal)
// ==========================================
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