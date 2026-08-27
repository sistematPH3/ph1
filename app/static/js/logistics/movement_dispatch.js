document.addEventListener('DOMContentLoaded', () => {
    const itemsBody = document.getElementById('itemsBody');
    const btnAddRow = document.getElementById('btnAddRow');
    const dispatchForm = document.getElementById('dispatchForm');
    const productOptionsTemplateEl = document.getElementById('productOptionsTemplate');
    const isReadOnly = dispatchForm ? dispatchForm.dataset.isReadOnly === 'true' : false;

    if (isReadOnly) {
        if (dispatchForm) {
            dispatchForm.querySelectorAll('input, select, button').forEach(el => {
                if (el.tagName !== 'A') {
                    el.disabled = true;
                }
            });
        }
        if (itemsBody) {
            itemsBody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-muted py-4">
                        <i class="bi bi-eye fs-3 d-block mb-2 text-secondary"></i>
                        <strong>Modo de solo lectura:</strong> No hay formulario activo para completar.
                    </td>
                </tr>`;
        }
        return;
    }

    if (!dispatchForm || !itemsBody || !productOptionsTemplateEl) return;

    const productOptionsTemplate = productOptionsTemplateEl.innerHTML;

    function getOriginLocationId() {
        const originSelect = document.getElementById('origin_location_id');
        if (originSelect && originSelect.disabled) {
            return document.getElementById('origin_location_id_hidden')?.value || originSelect.value;
        }
        return originSelect ? originSelect.value : '';
    }

    function getDestinationLocationId() {
        const destSelect = document.getElementById('destination_location_id');
        if (destSelect && destSelect.disabled) {
            return document.getElementById('destination_location_id_hidden')?.value || destSelect.value;
        }
        return destSelect ? destSelect.value : '';
    }

    function validateLocations() {
        const originSelect = document.getElementById('origin_location_id');
        const destSelect = document.getElementById('destination_location_id');
        const destFeedback = document.getElementById('destinationFeedback');
        const originId = getOriginLocationId();

        if (originSelect && !originSelect.disabled) {
            if (originId) {
                originSelect.classList.remove('is-invalid');
                originSelect.classList.add('is-valid');
            } else {
                originSelect.classList.remove('is-valid', 'is-invalid');
            }
        }

        if (!destSelect) return true;

        const destId = getDestinationLocationId();

        if (originId && destId && originId === destId) {
            destSelect.classList.remove('is-valid');
            destSelect.classList.add('is-invalid');
            if (destFeedback) {
                destFeedback.textContent = 'La sede de destino no puede ser igual a la sede de origen.';
            }
            return false;
        } else if (destId) {
            destSelect.classList.remove('is-invalid');
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

    document.getElementById('origin_location_id')?.addEventListener('change', () => {
        validateLocations();
        document.querySelectorAll('#itemsBody tr').forEach(row => checkStockForRow(row));
    });
    document.getElementById('destination_location_id')?.addEventListener('change', validateLocations);

    async function checkStockForRow(row) {
        const productSelect = row.querySelector('.product-select');
        const lotSelect = row.querySelector('.lot-select');
        const qtyInput = row.querySelector('.quantity-input');
        const expInput = row.querySelector('.exp-input');
        const totalStockInfo = row.querySelector('.total-stock-info');
        const maxHint = row.querySelector('.lot-max-hint');
        const qtyFeedback = qtyInput ? qtyInput.nextElementSibling : null;

        const originId = getOriginLocationId();
        const productId = productSelect.value;

        lotSelect.innerHTML = '<option value="" selected disabled>Cargando lotes...</option>';
        lotSelect.disabled = true;
        expInput.value = '';
        if (totalStockInfo) totalStockInfo.innerHTML = '';
        if (maxHint) maxHint.textContent = '';
        row.dataset.availableStock = 0;
        row.dataset.totalStock = 0;
        qtyInput.value = '';
        qtyInput.removeAttribute('max');
        qtyInput.classList.remove('is-invalid', 'is-valid');

        if (!originId || !productId) {
            lotSelect.innerHTML = '<option value="" selected disabled>Seleccione Lote...</option>';
            return;
        }

        try {
            const response = await fetch(`/logistics/movements/get-product-lots?location_id=${originId}&product_id=${productId}`);
            const data = await response.json();

            if (response.ok && data.success) {
                row.dataset.totalStock = data.total_stock;

                if (totalStockInfo) {
                    if (data.total_stock > 0) {
                        totalStockInfo.innerHTML = `
                            <span class="stock-badge stock-badge-available">
                                <i class="bi bi-box-seam me-1"></i> Stock Total: ${parseFloat(data.total_stock).toFixed(2)}
                            </span>`;
                    } else {
                        totalStockInfo.innerHTML = `
                            <span class="stock-badge stock-badge-empty">
                                <i class="bi bi-exclamation-triangle me-1"></i> Sin Stock en Sede
                            </span>`;
                    }
                }

                productSelect.classList.remove('is-invalid');
                productSelect.classList.add('is-valid');

                lotSelect.innerHTML = '<option value="" selected disabled>Seleccione Lote...</option>';

                if (!data.lots || data.lots.length === 0) {
                    lotSelect.innerHTML = '<option value="" selected disabled>Sin lotes registrados</option>';
                    qtyInput.classList.remove('is-valid');
                    qtyInput.classList.add('is-invalid');
                    if (qtyFeedback) qtyFeedback.textContent = 'Este insumo no posee partidas activas para transferir.';
                    return;
                }

                data.lots.forEach(lot => {
                    const option = document.createElement('option');
                    option.value = lot.lot_number;
                    option.textContent = `${lot.lot_number} (Disp: ${parseFloat(lot.available_quantity).toFixed(2)})`;
                    option.dataset.stock = lot.available_quantity;
                    option.dataset.expiration = lot.expiration_date;
                    lotSelect.appendChild(option);
                });

                lotSelect.disabled = false;
            } else {
                lotSelect.innerHTML = '<option value="" selected disabled>Error al cargar lotes</option>';
            }
        } catch (err) {
            lotSelect.innerHTML = '<option value="" selected disabled>Error de conexión</option>';
            lotSelect.disabled = true;
        }
    }

    function validateQuantityInput(row) {
        const qtyInput = row.querySelector('.quantity-input');
        const lotSelect = row.querySelector('.lot-select');
        const qtyFeedback = qtyInput ? qtyInput.nextElementSibling : null;
        const availableStock = parseFloat(row.dataset.availableStock || 0);
        const enteredQty = parseFloat(qtyInput.value) || 0;

        if (!lotSelect.value) {
            qtyInput.classList.remove('is-valid');
            if (enteredQty > 0) {
                qtyInput.classList.add('is-invalid');
                if (qtyFeedback) qtyFeedback.textContent = 'Debe seleccionar un lote primero.';
            }
            return;
        }

        if (qtyInput.value.trim() === '') {
            qtyInput.classList.remove('is-valid', 'is-invalid');
            return;
        }

        if (enteredQty <= 0) {
            qtyInput.classList.remove('is-valid');
            qtyInput.classList.add('is-invalid');
            if (qtyFeedback) qtyFeedback.textContent = 'La cantidad debe ser mayor a 0.';
        } else if (enteredQty > availableStock) {
            qtyInput.classList.remove('is-valid');
            qtyInput.classList.add('is-invalid');
            if (qtyFeedback) qtyFeedback.textContent = `Excede el disponible del lote (${availableStock.toFixed(2)}).`;
        } else {
            qtyInput.classList.remove('is-invalid');
            qtyInput.classList.add('is-valid');
        }
    }

    function updateAddButtonState() {
        const currentRowCount = itemsBody.querySelectorAll('tr').length;
        const limitWarning = document.getElementById('limitWarning');
        if (!btnAddRow) return;

        if (currentRowCount >= 25) {
            btnAddRow.style.pointerEvents = 'none';
            if (limitWarning) limitWarning.classList.remove('d-none');
        } else {
            btnAddRow.style.pointerEvents = 'auto';
            if (limitWarning) limitWarning.classList.add('d-none');
        }
    }

    function addRow() {
        const currentRowCount = itemsBody.querySelectorAll('tr').length;
        if (currentRowCount >= 25) return;

        const rowId = Date.now();
        const tr = document.createElement('tr');
        tr.id = `row-${rowId}`;

        tr.innerHTML = `
            <td>
                <select class="form-select ph-pill-input product-select" required>
                    ${productOptionsTemplate}
                </select>
                <div class="invalid-feedback ps-2">Seleccione un producto.</div>
                <small class="text-muted ps-2 pt-1 d-block total-stock-info"></small>
            </td>
            <td>
                <input type="number" step="0.01" min="0.01" max="999999.99" class="form-control ph-pill-input quantity-input text-center fw-bold" placeholder="0.00" required>
                <div class="invalid-feedback ps-2">La cantidad debe ser mayor a 0.</div>
                <div class="lot-max-hint text-center"></div>
            </td>
            <td>
                <select class="form-select ph-pill-input lot-select font-monospace" required disabled>
                    <option value="" selected disabled>Seleccione Lote...</option>
                </select>
                <div class="invalid-feedback ps-2">Debe seleccionar un lote.</div>
            </td>
            <td>
                <input type="date" class="form-control ph-pill-input exp-input bg-light text-center" readonly required>
                <div class="invalid-feedback ps-2">La fecha es obligatoria.</div>
            </td>
            <td class="text-center">
                <button type="button" class="btn btn-ph-delete btn-sm btn-delete shadow-sm" title="Eliminar fila">
                    <i class="bi bi-trash-fill"></i>
                </button>
            </td>
        `;

        const productSelect = tr.querySelector('.product-select');
        const lotSelect = tr.querySelector('.lot-select');
        const qtyInput = tr.querySelector('.quantity-input');
        const expInput = tr.querySelector('.exp-input');
        const maxHint = tr.querySelector('.lot-max-hint');

        productSelect.addEventListener('change', () => checkStockForRow(tr));
        
        qtyInput.addEventListener('keydown', (e) => {
            if (['-', '+', 'e', 'E'].includes(e.key)) {
                e.preventDefault();
            }
        });

        qtyInput.addEventListener('input', () => {
            if (parseFloat(qtyInput.value) < 0) {
                qtyInput.value = '';
            }
            validateQuantityInput(tr);
        });

        lotSelect.addEventListener('change', () => {
            const selectedOpt = lotSelect.options[lotSelect.selectedIndex];
            if (selectedOpt && selectedOpt.value) {
                const stock = parseFloat(selectedOpt.dataset.stock || 0);
                const expDate = selectedOpt.dataset.expiration || '';

                tr.dataset.availableStock = stock;
                expInput.value = expDate;
                qtyInput.value = '';
                qtyInput.setAttribute('max', stock.toFixed(2));
                qtyInput.classList.remove('is-invalid', 'is-valid');
                if (maxHint) maxHint.textContent = `Máx: ${stock.toFixed(2)}`;

                lotSelect.classList.remove('is-invalid');
                lotSelect.classList.add('is-valid');
                if (expDate) {
                    expInput.classList.remove('is-invalid');
                    expInput.classList.add('is-valid');
                }
            } else {
                tr.dataset.availableStock = 0;
                expInput.value = '';
                qtyInput.value = '';
                qtyInput.removeAttribute('max');
                if (maxHint) maxHint.textContent = '';
                lotSelect.classList.remove('is-valid');
                expInput.classList.remove('is-valid');
                qtyInput.classList.remove('is-invalid', 'is-valid');
            }
        });

        tr.querySelector('.btn-delete').addEventListener('click', () => {
            tr.remove();
            updateAddButtonState();
        });

        itemsBody.appendChild(tr);
        updateAddButtonState();
    }

    if (!isReadOnly) {
        addRow();
    }

    if (btnAddRow) {
        btnAddRow.addEventListener('click', addRow);
    }

    validateLocations();

    dispatchForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        dispatchForm.classList.add('was-validated');

        if (!validateLocations()) {
            document.getElementById('destination_location_id')?.focus();
            return;
        }

        const rows = itemsBody.querySelectorAll('tr');
        if (rows.length === 0) {
            return;
        }

        let formIsValid = true;
        rows.forEach(row => {
            const qtyInput = row.querySelector('.quantity-input');
            const productSelect = row.querySelector('.product-select');
            const lotSelect = row.querySelector('.lot-select');
            const expInput = row.querySelector('.exp-input');

            if (qtyInput?.classList.contains('is-invalid') || 
                productSelect?.classList.contains('is-invalid') ||
                lotSelect?.classList.contains('is-invalid') ||
                !lotSelect?.value ||
                !qtyInput?.value ||
                parseFloat(qtyInput.value) <= 0 ||
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
            const lotNumber = row.querySelector('.lot-select').value;
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

        const btnSubmit = document.getElementById('btnSubmit');
        const originalBtnHtml = btnSubmit.innerHTML;
        btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Procesando...';
        btnSubmit.disabled = true;

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
                btnSubmit.innerHTML = originalBtnHtml;
                btnSubmit.disabled = false;
                const errorMsg = result.errors ? result.errors.join('\n') : (result.message || 'Error en el despacho.');
                alert(`Error al procesar despacho:\n${errorMsg}`);
            }
        } catch (error) {
            btnSubmit.innerHTML = originalBtnHtml;
            btnSubmit.disabled = false;
            alert('Error de conexión con el servidor.');
        }
    });
});

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

            btnConfirmCancel.disabled = true;

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
                    setTimeout(() => { window.location.reload(); }, 1500);
                } else {
                    btnConfirmCancel.disabled = false;
                    const errorMsg = result.errors ? result.errors.join('\n') : (result.message || 'Error al cancelar.');
                    if (alertDiv) {
                        alertDiv.className = 'alert alert-danger py-2 small mb-3';
                        alertDiv.textContent = errorMsg;
                    }
                }
            } catch (error) {
                btnConfirmCancel.disabled = false;
                if (alertDiv) {
                    alertDiv.className = 'alert alert-danger py-2 small mb-3';
                    alertDiv.textContent = 'Error de conexión con el servidor.';
                }
            }
        });
    }
});