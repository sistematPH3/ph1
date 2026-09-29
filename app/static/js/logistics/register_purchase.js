let productOptionsHtml = '';

function parseNum(value) {
    if (typeof value === 'number') return value;
    if (typeof value !== 'string') return NaN;
    let s = String(value).trim().replace(/\s+/g, '');
    if (!s) return NaN;
    let sign = '';
    if (s[0] === '-') { sign = '-'; s = s.slice(1); }
    let norm;
    if (s.indexOf(',') !== -1) {
        // La coma es el separador decimal; los puntos son separadores de miles.
        norm = s.replace(/\./g, '').replace(',', '.');
    } else if (/^0+\.\d+$/.test(s)) {
        // Un punto tras un "0" inicial es decimal, no separador de miles:
        // "0.500" es medio, no 500 (error de 1000x). Debe coincidir con
        // normalizar_numero() del servidor.
        norm = s;
    } else {
        // Punto como separador de miles: punto seguido de exactamente 3 dígitos.
        norm = s.replace(/\.(?=\d{3}(?!\d))/g, '');
    }
    return parseFloat(sign + norm);
}

function updateSummary() {
    // El total se muestra en la confirmación del servidor; aquí solo se
    // evita un error si el bloque de resumen no está presente.
}

function updateRateLabel(currency) {
    const rateLabel = document.getElementById('rateLabel');
    if (!rateLabel) return;
    if (currency === 'BS') {
        rateLabel.innerText = 'Tasa de Referencia BCV (Bs por $)';
    } else if (currency === 'EUR') {
        rateLabel.innerText = 'Tasa de Cambio (BCV) — Bs por EUR';
    } else {
        rateLabel.innerText = 'Tasa de Cambio (BCV) — Bs por USD';
    }
}

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
    restoreDraft();

    const supplierSelect = document.getElementById('supplier_id');
    if (supplierSelect) {
        supplierSelect.addEventListener('change', function() {
            if (this.value === 'new') {
                saveDraft();
                window.location.href = this.getAttribute('data-new-url');
            } else {
                saveDraft();
            }
        });
    }

    const currencySelect = document.getElementById('currency');
    const rateInput = document.getElementById('exchange_rate');
    const refreshRateBtn = document.getElementById('refreshRateBtn');

    // Control de la peticion de tasa en vuelo. Cada llamada aborta la anterior
    // y ademas se marca con un token, para que una respuesta tardia que ya
    // escape al abort no pueda escribir una tasa de la moneda equivocada:
    // el usuario cambiaba de USD a EUR, llegaba tarde la consulta del USD y le
    // llenaba el campo con la tasa del dólar.
    let rateRequestSeq = 0;
    let rateController = null;

    async function fetchExchangeRate() {
        const selectedCurrency = currencySelect.value;

        if (rateController) {
            rateController.abort();
            rateController = null;
        }
        const requestSeq = ++rateRequestSeq;

        if (selectedCurrency === 'BS') {
            // En Bs el precio ya isIndependiente de la tasa, el campo queda
            // editable y es solo de referencia.
            rateInput.removeAttribute('readonly');
            rateInput.setAttribute('placeholder', 'Ingrese tasa BCV (Bs por $)');
            rateInput.classList.replace('text-muted', 'text-dark');
            return;
        }

        rateInput.value = '';
        rateInput.setAttribute('placeholder', 'Consultando...');
        rateInput.setAttribute('readonly', true);
        rateInput.classList.replace('text-dark', 'text-muted');
        
        const icon = refreshRateBtn.querySelector('i');
        icon.classList.add('bi-hourglass-split');
        icon.classList.remove('bi-arrow-clockwise');

        const controller = new AbortController();
        rateController = controller;
        const timeoutId = setTimeout(() => controller.abort(), 3000);

        try {
            const response = await fetch(`/bcv/api/get-rate?currency=${selectedCurrency}`, { 
                signal: controller.signal 
            });
            
            clearTimeout(timeoutId);

            // Esta consulta ya no es la vigente: se descarta su resultado.
            if (requestSeq !== rateRequestSeq) {
                return;
            }

            if (response.ok) {
                const data = await response.json();
                const rate = data.rate || data.tasa || data[selectedCurrency] || data.valor;

                if (rate) {
                    rateInput.value = parseFloat(rate).toFixed(4);
                    rateInput.setAttribute('readonly', true);
                    rateInput.removeAttribute('placeholder');
                    rateInput.classList.replace('text-dark', 'text-muted');
                    saveDraft();
                } else {
                    throw new Error("Formato de respuesta desconocido");
                }
            } else {
                throw new Error("Error en la API BCV");
            }
        } catch (error) {
            // Un abort de nuestra propia cancelacion no es un fallo a mostrar.
            if (error.name === 'AbortError' || requestSeq !== rateRequestSeq) {
                return;
            }
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
            // Solo restaura el icono la peticion vigente: si esta ya fue
            // cancelada, otra sigue cargando y el reloj debe quedarse.
            if (requestSeq === rateRequestSeq) {
                icon.classList.remove('bi-hourglass-split');
                icon.classList.add('bi-arrow-clockwise');
            }
        }
    }

    if (!rateInput.value) {
        fetchExchangeRate();
    } else {
        updateRateLabel(currencySelect.value);
    }

    currencySelect.addEventListener('change', () => {
        updateRateLabel(currencySelect.value);
        saveDraft();
        fetchExchangeRate();
    });

    refreshRateBtn.addEventListener('click', fetchExchangeRate);

    const manualRateBtn = document.getElementById('manualRateBtn');
    if (manualRateBtn) {
        manualRateBtn.addEventListener('click', () => {
            // Si el usuario decide escribirla a mano, la consulta en vuelo ya
            // no le sirve: si landingara despues le pisaria el valor que esta
            // escribiendo. Se cancela y se invalida con el mismo contador.
            if (rateController) {
                rateController.abort();
                rateController = null;
            }
            rateRequestSeq++;
            rateInput.removeAttribute('readonly');
            rateInput.classList.replace('text-muted', 'text-dark');
            rateInput.focus();
        });
    }

    rateInput.addEventListener('input', () => {
        const rateVal = parseNum(rateInput.value);
        if (rateVal > 999999.99) {
            rateInput.value = '999999.99';
        }
        if (rateInput.value.length > 12) {
            rateInput.value = rateInput.value.slice(0, 12);
        }
        saveDraft();
        updateSummary();
    });

    document.querySelectorAll('#itemsContainer tr.main-product-row').forEach(row => {
        attachRowValidationListeners(row);
    });
});

function saveDraft() {
    const draft = {
        supplier_id: document.getElementById('supplier_id') ? document.getElementById('supplier_id').value : '',
        currency: document.getElementById('currency') ? document.getElementById('currency').value : 'USD',
        exchange_rate: document.getElementById('exchange_rate') ? document.getElementById('exchange_rate').value : '',
        items: []
    };

    const rows = document.querySelectorAll('#itemsContainer tr.main-product-row');
    rows.forEach(row => {
        const prodId = row.querySelector('.prod-id') ? row.querySelector('.prod-id').value : '';
        const prodQty = row.querySelector('.prod-qty') ? row.querySelector('.prod-qty').value : '';
        const prodLot = row.querySelector('.prod-lot') ? row.querySelector('.prod-lot').value : '';
        const prodExp = row.querySelector('.prod-exp') ? row.querySelector('.prod-exp').value : '';
        const prodPrice = row.querySelector('.prod-price') ? row.querySelector('.prod-price').value : '';

        draft.items.push({
            product_id: prodId,
            quantity: prodQty,
            lot_number: prodLot,
            expiration_date: prodExp,
            foreign_price: prodPrice
        });
    });

    sessionStorage.setItem('purchase_draft_form', JSON.stringify(draft));
}

function restoreDraft() {
    const rawDraft = sessionStorage.getItem('purchase_draft_form');
    if (!rawDraft) return;

    try {
        const draft = JSON.parse(rawDraft);

        if (draft.supplier_id && draft.supplier_id !== 'new') {
            const supplierSelect = document.getElementById('supplier_id');
            if (supplierSelect) supplierSelect.value = draft.supplier_id;
        }

        if (draft.currency) {
            const currencySelect = document.getElementById('currency');
            if (currencySelect) currencySelect.value = draft.currency;
        }

        if (draft.exchange_rate) {
            const rateInput = document.getElementById('exchange_rate');
            if (rateInput) rateInput.value = draft.exchange_rate;
        }

        if (draft.items && draft.items.length > 0) {
            const tbody = document.getElementById('itemsContainer');
            tbody.innerHTML = '';

            draft.items.forEach(item => {
                const row = createProductRowElement();
                tbody.appendChild(row);
                attachRowValidationListeners(row);

                const prodId = row.querySelector('.prod-id');
                const prodQty = row.querySelector('.prod-qty');
                const prodLot = row.querySelector('.prod-lot');
                const prodExp = row.querySelector('.prod-exp');
                const prodPrice = row.querySelector('.prod-price');

                if (prodId && item.product_id) prodId.value = item.product_id;
                if (prodQty && item.quantity) prodQty.value = item.quantity;
                if (prodLot && item.lot_number) prodLot.value = item.lot_number;
                if (prodExp && item.expiration_date) prodExp.value = item.expiration_date;
                if (prodPrice && item.foreign_price) prodPrice.value = item.foreign_price;
            });
        }
    } catch (e) {
        sessionStorage.removeItem('purchase_draft_form');
    }
}

function clearDraft() {
    sessionStorage.removeItem('purchase_draft_form');
}

/**
 * Estado de la foto: 'vacia' | 'revisando' | 'aceptada' | 'rechazada'
 *
 * Antes, al montar cualquier archivo se pintaba el dropzone de verde con un
 * check, como si ya estuviera aprobado, y la imagen no se miraba hasta que se
 * le daba "registrar". El verde ahora solo aparece si el servidor confirma que
 * la foto sirve.
 */
let estadoFoto = 'vacia';
let revisionFotoEnCurso = 0;

function pintarEstadoFoto(estado, mensaje) {
    const display = document.getElementById('photoFileName');
    const icon = document.getElementById('cameraIcon');
    const dropzone = document.getElementById('dropzoneArea');
    const removeBtn = document.getElementById('removePhotoBtn');
    if (!display || !icon || !dropzone) return;

    const nombre = (estado === 'vacia')
        ? 'Toca aquí para tomar foto o abrir galería'
        : (display.dataset.nombre || 'Foto');

    display.classList.remove('text-muted', 'text-success', 'text-danger', 'text-warning');
    icon.classList.remove('bi-camera', 'bi-check-circle-fill',
                          'bi-x-circle-fill', 'bi-hourglass-split');
    icon.classList.remove('text-muted', 'text-success', 'text-danger', 'text-warning');
    dropzone.style.setProperty('border-style', 'dashed', 'important');

    if (estado === 'revisando') {
        display.innerText = 'Revisando la foto...';
        display.classList.add('text-warning');
        icon.classList.add('bi-hourglass-split', 'text-warning');
        dropzone.style.setProperty('border-color', '#b8860b', 'important');
        dropzone.style.setProperty('border-style', 'solid', 'important');
    } else if (estado === 'aceptada') {
        display.innerText = nombre;
        display.classList.add('text-success');
        icon.classList.add('bi-check-circle-fill', 'text-success');
        dropzone.style.setProperty('border-color', '#198754', 'important');
        dropzone.style.setProperty('border-style', 'solid', 'important');
    } else if (estado === 'rechazada') {
        display.innerText = nombre;
        display.classList.add('text-danger');
        icon.classList.add('bi-x-circle-fill', 'text-danger');
        dropzone.style.setProperty('border-color', '#dc3545', 'important');
        dropzone.style.setProperty('border-style', 'solid', 'important');
    } else {
        display.innerText = nombre;
        display.classList.add('text-muted');
        icon.classList.add('bi-camera', 'text-muted');
        dropzone.style.setProperty('border-color', '#adb5bd', 'important');
    }
    if (removeBtn) removeBtn.classList.remove('d-none');
}

/**
 * Pide al servidor que mire la foto. No decide nada: el submit la vuelve a
 * validar. Solo sirve para que el usuario sepa ya, sin recargar, si lo que
 * fotografio sirve.
 */
async function revisarFoto(archivo) {
    if (!archivo) return;

    const token = ++revisionFotoEnCurso;
    estadoFoto = 'revisando';
    clearPhotoError();
    pintarEstadoFoto('revisando');

    const formData = new FormData();
    formData.append('invoice_photo', archivo);

    try {
        const response = await fetch('/logistics/purchases/validar-foto', {
            method: 'POST',
            body: formData
        });
        const data = await response.json().catch(() => ({}));

        // Si el usuario quito la foto o monto otra mientras se revisaba, este
        // resultado ya es viejo y no debe pintar nada.
        if (token !== revisionFotoEnCurso) return;

        if (response.ok && data.puede_aceptar) {
            estadoFoto = 'aceptada';
            pintarEstadoFoto('aceptada');
        } else {
            estadoFoto = 'rechazada';
            pintarEstadoFoto('rechazada');
            const motivo = data.mensaje || data.error
                || 'La foto no se pudo confirmar como factura o comprobante.';
            setPhotoError(motivo);
        }
    } catch (error) {
        if (token !== revisionFotoEnCurso) return;
        // Si no hay conexion con el servidor no se marca la foto como buena:
        // se deja en revision y el submit vuelve a validarla.
        estadoFoto = 'vacia';
        pintarEstadoFoto('vacia');
    }
}

document.getElementById('invoice_photo').addEventListener('change', function(e) {
    const display = document.getElementById('photoFileName');
    if (display) display.dataset.nombre = this.files[0] ? this.files[0].name : '';

    clearPhotoError();

    if (this.files && this.files.length > 0) {
        revisarFoto(this.files[0]);
    } else {
        revisionFotoEnCurso++;
        estadoFoto = 'vacia';
        pintarEstadoFoto('vacia');
        const removeBtn = document.getElementById('removePhotoBtn');
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

// --- Errores del campo de foto -------------------------------------------------
// El dropzone es un <label>, no un .mariuska-select-group, asi que setFieldError
// no lo marca bien: ademas el borde lleva !important y hay que respetarlo.
function setPhotoError(message) {
    const input = document.getElementById('invoice_photo');
    const wrapper = input ? input.closest('.mb-2') : null;
    if (!wrapper) return;

    const previous = wrapper.querySelector('.error-label');
    if (previous) previous.remove();

    const errorDiv = document.createElement('div');
    errorDiv.className = 'text-danger small fw-bold mt-1 error-label animate-fade-in';
    errorDiv.style.fontSize = '0.78rem';
    errorDiv.style.whiteSpace = 'normal';
    errorDiv.innerText = message;
    wrapper.appendChild(errorDiv);

    const dropzone = document.getElementById('dropzoneArea');
    if (dropzone) {
        dropzone.style.setProperty('border-color', '#dc3545', 'important');
        dropzone.style.setProperty('border-style', 'solid', 'important');
    }
}

function clearPhotoError() {
    const input = document.getElementById('invoice_photo');
    const wrapper = input ? input.closest('.mb-2') : null;
    if (wrapper) {
        const existing = wrapper.querySelector('.error-label');
        if (existing) existing.remove();
    }

    const dropzone = document.getElementById('dropzoneArea');
    if (dropzone) {
        dropzone.style.removeProperty('border-color');
        dropzone.style.removeProperty('border-style');
        // Se restablece el estado visual por defecto del dropzone.
        dropzone.style.setProperty('border-color', '#adb5bd', 'important');
        dropzone.style.setProperty('border-style', 'dashed', 'important');
    }
}

// Convierte lo que devuelve el backend en texto plano seguro para SweetAlert.
// Los mensajes vienen del servidor, pero details puede traer str(excepcion), y
// eso si lleva contenido del usuario: se escapa antes de tocar el DOM.
function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = String(value);
    return div.innerHTML;
}

// Normaliza 'details' a una lista de cadenas. Acepta string, array o el
// diccionario campo -> mensaje que devuelve validate_create.
function collectErrorMessages(details) {
    if (!details) return [];

    let messages;
    if (typeof details === 'string') {
        messages = [details];
    } else if (Array.isArray(details)) {
        messages = details;
    } else if (typeof details === 'object') {
        messages = Object.values(details);
    } else {
        return [];
    }

    return messages
        .map(m => (m === null || m === undefined ? '' : String(m).trim()))
        .filter(m => m !== '');
}

function buildErrorList(details) {
    const messages = collectErrorMessages(details);
    if (messages.length === 0) return '';

    const items = messages
        .map(m => `<li>${escapeHtml(m)}</li>`)
        .join('');

    return `<ul style="text-align:left; margin:0.5rem 0 0 0; padding-left:1.25rem">${items}</ul>`;
}

// Version en texto plano para marcar el campo: innerText no interpreta HTML.
function plainErrorText(details) {
    return collectErrorMessages(details).join(' ');
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

function fechaLocalInput(d) {
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const dia = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}-${m}-${dia}`;
}

function configureDatePickerLimits(expInput) {
    if (!expInput) return;

    const minDateObj = new Date();
    minDateObj.setDate(minDateObj.getDate() + 1);
    expInput.min = fechaLocalInput(minDateObj);

    const maxDateObj = new Date();
    maxDateObj.setFullYear(maxDateObj.getFullYear() + 10);
    expInput.max = fechaLocalInput(maxDateObj);
}

function attachRowValidationListeners(row) {
    const prodId = row.querySelector('.prod-id');
    const prodQty = row.querySelector('.prod-qty');
    const prodLot = row.querySelector('.prod-lot');
    const prodPrice = row.querySelector('.prod-price');
    const expInput = row.querySelector('.prod-exp');

    configureDatePickerLimits(expInput);

    if (prodId) {
        prodId.addEventListener('change', () => {
            if (!prodId.value) {
                setFieldError(prodId, 'Selecciona producto.');
            } else {
                clearFieldError(prodId);
                
                const selectedOpt = prodId.options[prodId.selectedIndex];
                const days = parseInt(selectedOpt.getAttribute('data-days')) || 0;
                
                if (expInput) {
                    configureDatePickerLimits(expInput);

                    if (days > 0 && !expInput.value) {
                        const autoDateObj = new Date();
                        autoDateObj.setDate(autoDateObj.getDate() + days);
                        expInput.value = fechaLocalInput(autoDateObj);
                    }
                }
            }
            saveDraft();
        });
    }

    if (prodQty) {
        prodQty.addEventListener('input', () => {
            const val = parseNum(prodQty.value);
            if (!prodQty.value || isNaN(val)) {
                setFieldError(prodQty, 'La cantidad es obligatoria.');
            } else if (val < 0.01) {
                setFieldError(prodQty, 'Debe ser mayor o igual a 0.01.');
            } else if (val > 999999.99) {
                setFieldError(prodQty, 'Máximo 999.999,99');
            } else {
                clearFieldError(prodQty);
            }
            saveDraft();
            updateSummary();
        });
    }

    if (prodLot) {
        prodLot.addEventListener('input', () => {
            if (prodLot.value.length > 30) {
                prodLot.value = prodLot.value.slice(0, 30);
            }
            saveDraft();
        });
    }

    if (expInput) {
        expInput.addEventListener('change', saveDraft);
        expInput.addEventListener('input', saveDraft);
    }

    if (prodPrice) {
        prodPrice.addEventListener('input', () => {
            // parseNum y no parseFloat: el navegador interpreta "1.500" como
            // 1.5, así que con parseFloat una cantidad válida de 1500 se
            // comparaba contra el mínimo y el máximo como si fuera 1.5. El
            // aviso en vivo contradecía lo que después aceptaba el submit.
            const val = parseNum(prodPrice.value);
            if (!prodPrice.value || isNaN(val)) {
                setFieldError(prodPrice, 'El precio es obligatorio.');
            } else if (val < 0.01) {
                setFieldError(prodPrice, 'Debe ser mayor o igual a 0.01.');
            } else if (val > 999999999.99) {
                setFieldError(prodPrice, 'Máximo 999,999,999.99');
            } else {
                clearFieldError(prodPrice);
            }
            saveDraft();
        });
    }
}

function createProductRowElement() {
    const optionsHtml = productOptionsHtml || '<option value="">-- Elige un producto --</option>';
    const row = document.createElement('tr');
    row.className = 'main-product-row';
    row.innerHTML = `
        <td>
            <div class="table-field-wrapper">
                <div class="input-group mariuska-select-group">
                    <select class="form-select border-0 py-2 bg-transparent cursor-pointer prod-id" required>
                        ${optionsHtml}
                    </select>
                </div>
            </div>
        </td>
        <td>
            <div class="table-field-wrapper">
                <div class="input-group search-input-group">
                    <input type="text" inputmode="decimal" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-qty" placeholder="0.00" required>
                </div>
            </div>
        </td>
        <td>
            <div class="table-field-wrapper">
                <div class="input-group search-input-group">
                    <input type="text" maxlength="30" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-lot font-monospace" placeholder="Auto o Manual">
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
                    <input type="text" inputmode="decimal" class="form-control border-0 py-2 bg-transparent text-center fw-semibold prod-price" placeholder="Total línea" required>
                </div>
            </div>
        </td>
        <td class="text-center">
            <button type="button" class="btn btn-danger btn-sm rounded-circle d-inline-flex align-items-center justify-content-center shadow-sm" style="width: 34px; height: 34px; background-color: #dc3545; border: none;" onclick="this.closest('tr').remove(); saveDraft();" title="Eliminar">
                <i class="bi bi-trash text-white fs-6"></i>
            </button>
        </td>
    `;
    return row;
}

function addProductRow() {
    const tbody = document.getElementById('itemsContainer');
    const row = createProductRowElement();
    tbody.appendChild(row);
    attachRowValidationListeners(row);
    saveDraft();
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
    
    const rateVal = parseNum(exchangeRate.value);
    if (!exchangeRate.value || isNaN(rateVal) || rateVal < 0.01) { 
        setFieldError(exchangeRate, 'La tasa de cambio debe ser un número mayor o igual a 0.01.'); 
        isValid = false; 
    } else if (rateVal > 999999.99) {
        setFieldError(exchangeRate, 'La tasa máxima permitida es 999,999.99.');
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
    } else if (estadoFoto === 'rechazada') {
        // Ya sabemos que esa foto no es un comprobante: no tiene caso enviar
        // todo el formulario para que el servidor lo rechace. Se avisa aqui y
        // se manda a retomar la foto. El servidor igual la vuelve a validar.
        Swal.fire({
            icon: 'warning',
            title: 'La foto no es una factura',
            text: 'Vuelve a tomar la foto del comprobante. Tiene que verse completa, con el emisor, el RIF y los importes legibles.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Volver a tomar la foto'
        });
        isValid = false;
    } else if (estadoFoto === 'revisando') {
        // La revision sigue en curso: todavia no se sabe si la foto sirve, y
        // mandarla ahora seria tirar el trabajo del usuario a la basura.
        Swal.fire({
            icon: 'info',
            title: 'Un momento',
            text: 'Todavía se está revisando la foto de la factura. Espera a que termine e inténtalo de nuevo.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Entendido'
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
        
        const qtyVal = parseNum(prodQty.value);
        if (!prodQty.value || isNaN(qtyVal)) { 
            setFieldError(prodQty, 'La cantidad es obligatoria.'); 
            isValid = false; 
        } else if (qtyVal < 0.01) { 
            setFieldError(prodQty, 'Debe ser mayor o igual a 0.01.'); 
            isValid = false; 
        } else if (qtyVal > 999999.99) {
            setFieldError(prodQty, 'Máximo 999,999.99');
            isValid = false;
        }
        
        const priceVal = parseNum(prodPrice.value);
        if (!prodPrice.value || isNaN(priceVal)) { 
            setFieldError(prodPrice, 'El precio es obligatorio.'); 
            isValid = false; 
        } else if (priceVal < 0.01) { 
            setFieldError(prodPrice, 'Debe ser mayor o igual a 0.01.'); 
            isValid = false; 
        } else if (priceVal > 999999999.99) {
            setFieldError(prodPrice, 'Máximo 999,999,999.99');
            isValid = false;
        }
    });

    return isValid;
}

// Evita que un doble clic registre DOS compras. El formulario se bloquea
// mientras la peticion esta en vuelo y se desbloquea si algo falla, para que
// el usuario pueda reintentar sin recargar la pagina.
let envioEnCurso = false;

document.getElementById('purchaseForm').addEventListener('submit', async (e) => {
    e.preventDefault(); 

    if (envioEnCurso) {
        return;
    }

    if (!validateFormBeforeSubmit()) {
        const firstError = document.querySelector('.error-label');
        if (firstError) {
            firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return; 
    }

    envioEnCurso = true;
    const botonEnviar = document.querySelector(
        '#purchaseForm button[type="submit"], #purchaseForm .submit-btn, #btnRegistrar');
    const textoOriginalBoton = botonEnviar ? botonEnviar.innerHTML : null;
    if (botonEnviar) {
        botonEnviar.disabled = true;
        botonEnviar.innerHTML = 'Registrando...';
    }

    const formData = new FormData();
    formData.append('supplier_id', document.getElementById('supplier_id').value);
    formData.append('currency', document.getElementById('currency').value);
    // Se manda el TEXTO que el usuario escribio, no un numero ya parseado.
    // Al reformatar aqui se perdia la convencion venezolana: "10,335" salia
    // como "10.335" y el servidor, que aplica la misma convencion, leia el
    // punto como separador de miles y guardaba 10335. La normalizacion se
    // aplica una sola vez, en el servidor, sobre lo que el usuario escribio.
    formData.append('exchange_rate', document.getElementById('exchange_rate').value);
    formData.append('user_id', document.getElementById('user_id').value);

    const photoFile = document.getElementById('invoice_photo').files[0];
    formData.append('invoice_photo', photoFile);

    const rows = document.querySelectorAll('#itemsContainer tr.main-product-row');
    rows.forEach(row => {
        const prodIdVal = row.querySelector('.prod-id').value;
        const qtyVal = row.querySelector('.prod-qty').value;
        const lotVal = row.querySelector('.prod-lot') ? row.querySelector('.prod-lot').value : '';
        const expVal = row.querySelector('.prod-exp').value;
        const priceVal = row.querySelector('.prod-price').value;

        if (prodIdVal) {
            formData.append('product_id[]', prodIdVal);
            formData.append('quantity[]', qtyVal);
            formData.append('lot_number[]', lotVal);
            formData.append('expiration_date[]', expVal);
            formData.append('foreign_price[]', priceVal);
        }
    });

    try {
        const response = await fetch('/logistics/purchases', {
            method: 'POST',
            body: formData
        });

        // No se asumir que la respuesta es JSON. Un 413 del proxy (foto muy
        // grande), un 500 con pagina de error en HTML o un 302 al login
        // hacian que response.json() lanzara, y el catch de abajo lo reportaba
        // como "Fallo de Conexion", que no es lo que paso: el servidor si
        // respondio.
        const textoRespuesta = await response.text();
        let result = {};
        try {
            result = textoRespuesta ? JSON.parse(textoRespuesta) : {};
        } catch (e) {
            result = {};
        }

        // Sesion vencida o sin permisos: un HTML de login no es JSON.
        if (response.redirected || response.status === 401 || response.status === 403) {
            Swal.fire({
                icon: 'warning',
                title: 'Sesión no válida',
                text: 'Tu sesión expiró o no tienes permiso para registrar compras. Vuelve a iniciar sesión; no se guardó nada.',
                confirmButtonColor: '#B31F24',
                confirmButtonText: 'Cerrar'
            });
            return;
        }

        if (response.status === 413) {
            setPhotoError('La foto es demasiado pesada para el servidor. Usa una imagen más pequeña.');
            Swal.fire({
                icon: 'warning',
                title: 'Foto demasiado grande',
                text: 'La imagen supera el tamaño permitido. Vuelve a tomarla con menos resolución y subela de nuevo.',
                confirmButtonColor: '#B31F24',
                confirmButtonText: 'Volver a tomar la foto'
            });
            return;
        }

        if (response.status >= 500) {
            Swal.fire({
                icon: 'error',
                title: 'Error del servidor',
                text: 'El sistema falló al guardar la compra. No se registró nada: inténtalo de nuevo en un momento.',
                confirmButtonColor: '#B31F24',
                confirmButtonText: 'Cerrar'
            });
            return;
        }

        if (response.ok) {
            clearDraft();

            // Aviso sobre la foto: si el backend no la pudo confirmar como
            // factura o comprobante, el boton de exito no alcanza. Se cambia el
            // icono y el texto para que el usuario se entere antes de cerrar.
            const foto = result.factura || {};
            const facturaOk = foto.aceptada === true;
            const titulo = facturaOk
                ? '¡Compra registrada!'
                : '¡Compra registrada, con un aviso!';
            const texto = facturaOk
                ? 'Compra realizada con éxito'
                : (foto.mensaje || 'La foto adjunta no pudo verificarse.');

            Swal.fire({
                icon: facturaOk ? 'success' : 'warning',
                title: titulo,
                text: texto,
                confirmButtonColor: facturaOk ? '#198754' : '#b8860b',
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
            // Antes esta rama miraba 'details' y mostraba "Error de
            // consistencia en el Servidor", tirando el mensaje real, y para el
            // resto leia 'message', clave que el backend no manda (usa 'error').
            // Resultado: el usuario veia "Ocurrio un error" sin saber si la
            // culpa era su foto o del sistema.
            const listaErrores = buildErrorList(result.details);
            const esFoto = result.campo === 'invoice_photo';

            if (esFoto) {
                setPhotoError(plainErrorText(result.details) || result.error || '');
            }

            Swal.fire({
                icon: esFoto ? 'warning' : 'error',
                title: result.error || 'No se pudo registrar la compra.',
                html: listaErrores || 'Revisa los datos del formulario e intentalo de nuevo.',
                confirmButtonColor: '#B31F24',
                confirmButtonText: esFoto ? 'Volver a tomar la foto' : 'Cerrar',
                customClass: { popup: 'rounded-4' }
            }).then(() => {
                if (!esFoto) return;
                // Se enfoca el selector para que el usuario rehaga la foto sin
                // buscar el campo. El formulario NO se limpia: lo que ya
                // escribio sigue ahi y solo falta cambiar la imagen.
                const input = document.getElementById('invoice_photo');
                if (input) {
                    input.value = '';
                    input.dispatchEvent(new Event('change'));
                    document.getElementById('dropzoneArea').scrollIntoView({
                        behavior: 'smooth', block: 'center'
                    });
                }
            });
        }
    } catch (error) {
        Swal.fire({
            icon: 'error',
            title: 'Fallo de Conexión',
            text: 'No se pudo conectar con el servidor backend.',
            confirmButtonColor: '#B31F24',
            confirmButtonText: 'Cerrar'
        });
    } finally {
        // El boton se desbloquea siempre. En el exito no molesta porque el
        // formulario se limpia y se rearma; si no, el usuario se quedaria con
        // un boton morto y sin poder reintentar tras un fallo.
        envioEnCurso = false;
        if (botonEnviar) {
            botonEnviar.disabled = false;
            if (textoOriginalBoton !== null) {
                botonEnviar.innerHTML = textoOriginalBoton;
            }
        }
    }
});
