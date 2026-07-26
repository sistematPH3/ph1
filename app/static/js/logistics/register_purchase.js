let productOptionsHtml = '';

document.addEventListener('DOMContentLoaded', () => {
    const productsCard = document.getElementById('productsCard');
    const invoiceCard = document.getElementById('invoiceCard');
    
    if (productsCard && invoiceCard && window.innerWidth >= 992) {
        const initialMaxHeight = Math.max(productsCard.offsetHeight, invoiceCard.offsetHeight);
        productsCard.style.minHeight = `${initialMaxHeight}px`;
        invoiceCard.style.minHeight = `${initialMaxHeight}px`;
    }

    const initialSelect = document.querySelector('.prod-id');
    if (initialSelect) {
        productOptionsHtml = initialSelect.innerHTML;
    }

    setupHeaderValidation();

    const supplierSelect = document.getElementById('supplier_id');
    if (supplierSelect) {
        supplierSelect.addEventListener('change', function() {
            if (this.value === 'new') {
                window.location.href = this.getAttribute('data-new-url');
            }
        });
    }

    const currencySelect = document.getElementById('currency');
    const rateInput = document.getElementById('exchange_rate');
    const refreshRateBtn = document.getElementById('refreshRateBtn');

    async function fetchExchangeRate() {
        const selectedCurrency = currencySelect.value;
        
        rateInput.value = '';
        rateInput.setAttribute('placeholder', 'Consultando...');
        rateInput.setAttribute('readonly', true);
        rateInput.classList.replace('text-dark', 'text-muted');
        
        const icon = refreshRateBtn.querySelector('i');
        icon.classList.add('bi-hourglass-split');
        icon.classList.remove('bi-arrow-clockwise');

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);

        try {
            const response = await fetch(`/bcv/api/get-rate?currency=${selectedCurrency}`, { 
                signal: controller.signal 
            });
            
            clearTimeout(timeoutId);

            if (response.ok) {
                const data = await response.json();
                const rate = data.rate || data.tasa || data[selectedCurrency] || data.valor;

                if (rate) {
                    rateInput.value = parseFloat(rate).toFixed(4);
                    rateInput.setAttribute('readonly', true);
                    rateInput.removeAttribute('placeholder');
                    rateInput.classList.replace('text-dark', 'text-muted');
                } else {
                    throw new Error("Formato de respuesta desconocido");
                }
            } else {
                throw new Error("Error en la API BCV");
            }
        } catch (error) {
            rateInput.value = '';
            rateInput.removeAttribute('readonly');
            rateInput.setAttribute('placeholder', 'Ingrese tasa manual');
            rateInput.classList.replace('text-muted', 'text-dark');
            
            Swal.fire({
                icon: 'warning',
                title: 'Conexión BCV Fallida',
                text: 'No se pudo obtener la tasa automáticamente. Por favor, ingrese la tasa de cambio manualmente.',
                confirmButtonColor: '#dc3545',
                confirmButtonText: 'Entendido'
            });
        } finally {
            icon.classList.remove('bi-hourglass-split');
            icon.classList.add('bi-arrow-clockwise');
        }
    }

    fetchExchangeRate();
    currencySelect.addEventListener('change', fetchExchangeRate);
    refreshRateBtn.addEventListener('click', fetchExchangeRate);
});

document.getElementById('invoice_photo').addEventListener('change', function(e) {
    const fileNameDisplay = document.getElementById('photoFileName');
    const icon = document.getElementById('cameraIcon');
    const dropzone = document.getElementById('dropzoneArea');
    const removeBtn = document.getElementById('removePhotoBtn');
    
    if (this.files && this.files.length > 0) {
        fileNameDisplay.innerText = this.files[0].name;
        fileNameDisplay.classList.replace('text-muted', 'text-success');
        icon.classList.replace('bi-camera', 'bi-check-circle-fill');
        icon.classList.replace('text-muted', 'text-success');
        dropzone.style.borderColor = '#198754';
        if (removeBtn) removeBtn.classList.remove('d-none');
    } else {
        fileNameDisplay.innerText = 'Toca aquí para tomar foto o abrir galería';
        fileNameDisplay.classList.replace('text-success', 'text-muted');
        icon.classList.replace('bi-check-circle-fill', 'bi-camera');
        icon.classList.replace('text-success', 'text-muted');
        dropzone.style.borderColor = '#adb5bd';
        if (removeBtn) removeBtn.classList.add('d-none');
    }
});

const removePhotoBtn = document.getElementById('removePhotoBtn');
if (removePhotoBtn) {
    removePhotoBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const fileInput = document.getElementById('invoice_photo');
        fileInput.value = '';
        fileInput.dispatchEvent(new Event('change'));
    });
}

function setFieldError(element, message) {
    if (!element) return;
    
    const wrapper = element.closest('.mb-3') || element.closest('.mb-2') || element.closest('.table-field-wrapper');
    const inputGroup = element.closest('.mariuska-select-group') || element.closest('.search-input-group');
    
    clearFieldError(element);

    const errorDiv = document.createElement('div');
    errorDiv.className = 'text-danger small fw-bold mt-1 error-label animate-fade-in';
    errorDiv.style.fontSize = '0.78rem';
    errorDiv.style.whiteSpace = 'nowrap'; 
    errorDiv.innerText = message;
    
    wrapper.appendChild(errorDiv);

    if (inputGroup) {
        inputGroup.style.setProperty('border-color', '#dc3545', 'important');
    }
}

function clearFieldError(element) {
    if (!element) return;
    const wrapper = element.closest('.mb-3') || element.closest('.mb-2') || element.closest('.table-field-wrapper');
    const inputGroup = element.closest('.mariuska-select-group') || element.closest('.search-input-group');
    
    const existingError = wrapper.querySelector('.error-label');
    if (existingError) {
        existingError.remove();
    }

    if (inputGroup) {
        inputGroup.style.borderColor = '';
    }
}

function setupHeaderValidation() {
    const fields = [
        { id: 'supplier_id', type: 'change', msg: 'Debes seleccionar un proveedor.' },
        { id: 'user_id', type: 'change', msg: 'Debes seleccionar un usuario comprador.' },
        { id: 'currency', type: 'change', msg: 'Debes seleccionar una moneda.' }
    ];

    fields.forEach(field => {
        const el = document.getElementById(field.id);
        if (el) {
            el.addEventListener(field.type, () => {
                if (!el.value || el.value === 'new') setFieldError(el, field.msg);
                else clearFieldError(el);
            });
        }
    });
}

function attachRowValidationListeners(row) {
    const prodId = row.querySelector('.prod-id');
    const prodQty = row.querySelector('.prod-qty');
    const prodPrice = row.querySelector('.prod-price');
    const expInput = row.querySelector('.prod-exp');

    const today = new Date().toISOString().split('T')[0];

    if (expInput) {
        expInput.min = today;
    }

    if (prodId) {
        prodId.addEventListener('change', () => {
            if (!prodId.value) {
                setFieldError(prodId, 'Selecciona producto.');
            } else {
                clearFieldError(prodId);
                
                const selectedOpt = prodId.options[prodId.selectedIndex];
                const days = parseInt(selectedOpt.getAttribute('data-days')) || 0;
                
                if (expInput) {
                    expInput.min = today;

                    if (days > 0) {
                        const autoDateObj = new Date();
                        autoDateObj.setDate(autoDateObj.getDate() + days);
                        const autoDateStr = autoDateObj.toISOString().split('T')[0];

                        expInput.max = autoDateStr;
                        expInput.value = autoDateStr;

                    } else {
                        const MAX_LOGICAL_MANUAL_DAYS = 365; 

                        const maxManualObj = new Date();
                        maxManualObj.setDate(maxManualObj.getDate() + MAX_LOGICAL_MANUAL_DAYS);
                        const maxManualStr = maxManualObj.toISOString().split('T')[0];

                        expInput.max = maxManualStr;
                        expInput.value = '';
                    }
                }
            }
        });
    }

    if (prodQty) {
        prodQty.addEventListener('input', () => {
            const val = parseFloat(prodQty.value);
            if (!prodQty.value || isNaN(val)) {
                setFieldError(prodQty, 'La cantidad es obligatoria.');
            } else if (val <= 0) {
                setFieldError(prodQty, 'Debe ser mayor a 0.');
            } else {
                clearFieldError(prodQty);
            }
        });
    }

    if (prodPrice) {
        prodPrice.addEventListener('input', () => {
            const val = parseFloat(prodPrice.value);
            if (!prodPrice.value || isNaN(val)) {
                setFieldError(prodPrice, 'El precio es obligatorio.');
            } else if (val <= 0) {
                setFieldError(prodPrice, 'Debe ser mayor a 0.');
            } else {
                clearFieldError(prodPrice);
            }
        });
    }
}

document.querySelectorAll('#itemsContainer tr.main-product-row').forEach(row => {
    attachRowValidationListeners(row);
    
    const prodId = row.querySelector('.prod-id');
    if (prodId && prodId.value) {
        prodId.dispatchEvent(new Event('change'));
    }
});

function addProductRow() {
    const tbody = document.getElementById('itemsContainer');
    const optionsHtml = productOptionsHtml || '<option value="">-- Elige un producto --</option>';

    const row = document.createElement('tr');
    row.className = 'main-product-row';
    row.innerHTML = `
        <td>
            <div class="table-field-wrapper">
                <div class="input-group mariuska-select-group">
                    <select class="form-select border-0 py-2 bg-transparent cursor-pointer prod-id">
                        ${optionsHtml}
                    </select>
                </div>
            </div>
        </td>
        <td>
            <div class="table-field-wrapper">
                <div class="input-group search-input-group">
                    <input type="number" step="0.01" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-qty">
                </div>
            </div>
        </td>
        <td>
            <div class="table-field-wrapper">
                <div class="input-group search-input-group">
                    <input type="date" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-exp">
                </div>
            </div>
        </td>
        <td>
            <div class="table-field-wrapper">
                <div class="input-group search-input-group">
                    <span class="input-group-text bg-transparent border-0 text-muted ps-2 pe-1"><i class="bi bi-currency-exchange"></i></span>
                    <input type="number" step="0.01" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-price">
                </div>
            </div>
        </td>
        <td class="text-center">
            <button type="button" class="btn btn-danger btn-sm rounded-circle d-inline-flex align-items-center justify-content-center shadow-sm" style="width: 34px; height: 34px; background-color: #dc3545; border: none;" onclick="this.closest('tr').remove()" title="Eliminar">
                <i class="bi bi-trash text-white fs-6"></i>
            </button>
        </td>
    `;
    tbody.appendChild(row);

    attachRowValidationListeners(row);
}

function validateFormBeforeSubmit() {
    let isValid = true;

    const supplier = document.getElementById('supplier_id');
    const user = document.getElementById('user_id');
    const currency = document.getElementById('currency');
    const exchangeRate = document.getElementById('exchange_rate');
    const invoicePhoto = document.getElementById('invoice_photo');

    if (!supplier.value || supplier.value === 'new') { setFieldError(supplier, 'Debes seleccionar un proveedor.'); isValid = false; }
    if (!user.value) { setFieldError(user, 'Debes seleccionar un usuario comprador.'); isValid = false; }
    if (!currency.value) { setFieldError(currency, 'Debes seleccionar una moneda.'); isValid = false; }
    
    const rateVal = parseFloat(exchangeRate.value);
    if (!exchangeRate.value || isNaN(rateVal) || rateVal <= 0) { 
        setFieldError(exchangeRate, 'La tasa de cambio debe ser un número mayor a cero.'); 
        isValid = false; 
    }

    if (!invoicePhoto.files || invoicePhoto.files.length === 0) {
        Swal.fire({
            icon: 'warning',
            title: 'Evidencia Requerida',
            text: 'Debes adjuntar la foto de la factura.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Cerrar'
        });
        isValid = false;
    }

    const rows = document.querySelectorAll('#itemsContainer tr.main-product-row');
    if (rows.length === 0) {
        Swal.fire({
            icon: 'warning',
            title: 'Carrito Vacío',
            text: 'Debes registrar al menos un producto en la compra.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Cerrar'
        });
        isValid = false;
    }

    rows.forEach(row => {
        const prodId = row.querySelector('.prod-id');
        const prodQty = row.querySelector('.prod-qty');
        const prodPrice = row.querySelector('.prod-price');

        if (!prodId.value) { setFieldError(prodId, 'Selecciona producto.'); isValid = false; }
        
        const qtyVal = parseFloat(prodQty.value);
        if (!prodQty.value || isNaN(qtyVal)) { 
            setFieldError(prodQty, 'La cantidad es obligatoria.'); 
            isValid = false; 
        } else if (qtyVal <= 0) { 
            setFieldError(prodQty, 'Debe ser mayor a 0.'); 
            isValid = false; 
        }
        
        const priceVal = parseFloat(prodPrice.value);
        if (!prodPrice.value || isNaN(priceVal)) { 
            setFieldError(prodPrice, 'El precio es obligatorio.'); 
            isValid = false; 
        } else if (priceVal <= 0) { 
            setFieldError(prodPrice, 'Debe ser mayor a 0.'); 
            isValid = false; 
        }
    });

    return isValid;
}

document.getElementById('purchaseForm').addEventListener('submit', async (e) => {
    e.preventDefault(); 

    if (!validateFormBeforeSubmit()) {
        const firstError = document.querySelector('.error-label');
        if (firstError) {
            firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return; 
    }

    const formData = new FormData();
    formData.append('supplier_id', document.getElementById('supplier_id').value);
    formData.append('currency', document.getElementById('currency').value);
    formData.append('exchange_rate', document.getElementById('exchange_rate').value);
    formData.append('user_id', document.getElementById('user_id').value);
    
    const photoFile = document.getElementById('invoice_photo').files[0];
    formData.append('invoice_photo', photoFile);

    const rows = document.querySelectorAll('#itemsContainer tr.main-product-row');
    rows.forEach(row => {
        const prodIdVal = row.querySelector('.prod-id').value;
        const qtyVal = row.querySelector('.prod-qty').value;
        const expVal = row.querySelector('.prod-exp').value;
        const priceVal = row.querySelector('.prod-price').value;

        if(prodIdVal) {
            formData.append('product_id[]', prodIdVal);
            formData.append('quantity[]', qtyVal);
            formData.append('expiration_date[]', expVal);
            formData.append('foreign_price[]', priceVal);
        }
    });

    try {
        const response = await fetch('/logistics/purchases', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            Swal.fire({
                icon: 'success',
                title: '¡Compra registrada!',
                text: 'Compra realizada con éxito',
                confirmButtonColor: '#198754',
                confirmButtonText: 'Aceptar',
                customClass: {
                    popup: 'rounded-4'
                }
            }).then(() => {
                document.getElementById('purchaseForm').reset();
                
                document.querySelectorAll('.error-label').forEach(el => el.remove());
                document.querySelectorAll('.mariuska-select-group, .search-input-group').forEach(el => {
                    el.style.borderColor = '';
                });

                document.getElementById('itemsContainer').innerHTML = '';
                
                addProductRow();
                
                document.getElementById('invoice_photo').dispatchEvent(new Event('change'));
                
                document.getElementById('currency').dispatchEvent(new Event('change'));
            });
        } else {
            if (result.details) {
                Swal.fire({
                    icon: 'error',
                    title: 'Error de consistencia',
                    text: 'Se encontraron errores de consistencia en el Servidor.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
            } else {
                Swal.fire({
                    icon: 'error',
                    title: 'Oops...',
                    text: result.message || 'Ocurrió un error al procesar la compra.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
            }
        }
    } catch (error) {
        Swal.fire({
            icon: 'error',
            title: 'Fallo de Conexión',
            text: 'No se pudo conectar con el servidor backend.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Cerrar'
        });
    }
});