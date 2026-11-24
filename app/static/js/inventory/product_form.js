// static/js/inventory/product_form.js

document.addEventListener('DOMContentLoaded', () => {
    // =========================================================================
    // 1. REFERENCIAS A ELEMENTOS DEL DOM
    // =========================================================================
    const mainForm = document.querySelector('form[action*="product"]');
    const nameInput = document.getElementById('name');
    const productTypeSelect = document.getElementById('product_type_id');
    const unitSelect = document.getElementById('unit_of_measure_select');
    const unitCustomInput = document.getElementById('unit_of_measure_custom');
    const skuInput = document.getElementById('sku');
    const wasteLimitInput = document.getElementById('waste_limit');
    const minStockInput = document.getElementById('min_stock');
    const submitBtn = document.getElementById('btn-submit');
    const nameRealtimeError = document.getElementById('name-realtime-error');
    const checkNameUrl = mainForm ? mainForm.dataset.checkNameUrl : '';
    const currentProductId = mainForm ? mainForm.dataset.productId : '';
    let nameAlreadyExists = false;
    let nameCheckTimer = null;
    let nameCheckRequestId = 0;

    // Elementos del Modal de Categoría
    const modalOverlay = document.getElementById('categoryModalOverlay');
    const btnCloseModal = document.getElementById('btnCloseCategoryModal');
    const btnCancelModal = document.getElementById('btnCancelCategoryModal');
    const quickCategoryForm = document.getElementById('quickCategoryForm');
    const modalErrorBox = document.getElementById('modalCategoryError');
    const modalCatNameInput = document.getElementById('modal_cat_name');
    const catNameError = document.getElementById('modal_cat_name_error');

    const modalExpirationRadios = document.querySelectorAll('#quickCategoryForm input[name="expiration_control"]');
    const modalShelfLifeContainer = document.getElementById('modal_shelf_life_days_container');
    const modalShelfLifeInput = document.getElementById('modal_shelf_life_days');
    const modalExpirationError = document.getElementById('modal_expiration_control_error');
    const modalShelfLifeError = document.getElementById('modal_shelf_life_days_error');

    let lastSelectedProductType = productTypeSelect ? productTypeSelect.value : '';

    // FUNCIÓN HELPER: NORMALIZAR TEXTO (QUITA TILDES, COLAPSA CARACTERES REPETIDOS Y REMUEVE PLURALES)
    function normalizeText(text) {
        if (!text) return '';
        return text
            .trim()
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "") // "hortalizás" -> "hortalizas"
            .replace(/(.)\1+/g, "$1")         // "hortalizaaaaa" -> "hortaliza"
            .replace(/(es|s)$/g, "");         // "hortalizas" -> "hortaliza"
    }

    // =========================================================================
    // 2. SISTEMA DE VALIDACIONES DEL FORMULARIO PRINCIPAL
    // =========================================================================
    function showFieldError(inputElement, message) {
        clearFieldError(inputElement);
        
        const errorSpan = document.createElement('span');
        errorSpan.className = 'error-text js-validation-error';
        errorSpan.style.display = 'block';
        errorSpan.textContent = message;

        inputElement.parentNode.appendChild(errorSpan);

        inputElement.style.borderColor = '#d62300';
    }

    function clearFieldError(inputElement) {
        if (!inputElement) return;
        inputElement.style.borderColor = '';
        const existingError = inputElement.parentNode.querySelector('.js-validation-error');
        if (existingError) existingError.remove();
    }

    function validateName() {
        if (!nameInput.value.trim()) {
            showFieldError(nameInput, 'El nombre del producto es obligatorio.');
            return false;
        }
        clearFieldError(nameInput);
        return true;
    }

    function validateProductType() {
        if (!productTypeSelect.value) {
            showFieldError(productTypeSelect, 'Debe seleccionar un tipo de producto.');
            return false;
        }
        clearFieldError(productTypeSelect);
        return true;
    }

    function validateUnit() {
        if (!unitSelect.value) {
            showFieldError(unitSelect, 'Debe seleccionar una unidad de medida.');
            return false;
        }
        clearFieldError(unitSelect);

        if (unitSelect.value === 'OTHER') {
            if (!unitCustomInput.value.trim()) {
                showFieldError(unitCustomInput, 'Especifique la nueva unidad de medida.');
                return false;
            }
            if (unitCustomInput.value.trim().length > 100) {
                showFieldError(unitCustomInput, 'La unidad no puede exceder los 100 caracteres.');
                return false;
            }
            clearFieldError(unitCustomInput);
        }
        return true;
    }
    function validateSKU() {
        if (!skuInput.value.trim()) {
            showFieldError(skuInput, 'El SKU es obligatorio.');
            return false;
        }
        clearFieldError(skuInput);
        return true;
    }

    // ---------------------------------------------------------------------
    // VALIDACIÓN EN TIEMPO REAL DEL NOMBRE (DUPLICADOS)
    // ---------------------------------------------------------------------
    function setNameExists(exists) {
        nameAlreadyExists = exists;
        if (nameRealtimeError) {
            nameRealtimeError.style.display = exists ? 'block' : 'none';
        }
        if (nameInput) {
            nameInput.style.borderColor = exists ? '#d62300' : '';
            nameInput.setAttribute('aria-invalid', exists ? 'true' : 'false');
        }
        if (submitBtn) {
            submitBtn.disabled = exists;
            submitBtn.setAttribute('aria-disabled', exists ? 'true' : 'false');
        }
    }

    async function checkNameAvailability() {
        if (!nameInput || !checkNameUrl) return;

        const name = nameInput.value.trim();
        if (!name) {
            setNameExists(false);
            return;
        }

        const requestId = ++nameCheckRequestId;
        const params = new URLSearchParams({ name });
        // En edición el propio insumo no debe contarse como duplicado.
        if (currentProductId) params.set('exclude_id', currentProductId);

        try {
            const response = await fetch(checkNameUrl + '?' + params.toString(), {
                headers: { 'Accept': 'application/json' }
            });
            if (!response.ok) return;

            const result = await response.json();
            // Descarta respuestas antiguas si el usuario siguió escribiendo.
            if (requestId !== nameCheckRequestId) return;
            setNameExists(Boolean(result.exists));
        } catch (err) {
            // Un fallo de red no bloquea el guardado: el backend vuelve a
            // validar el duplicado al enviar el formulario.
            console.error('No se pudo verificar el nombre del insumo:', err);
        }
    }

    function scheduleNameCheck() {
        if (nameCheckTimer) clearTimeout(nameCheckTimer);
        nameCheckTimer = setTimeout(checkNameAvailability, 350);
    }

    // Límite real de una columna NUMERIC(10, 2) en la base de datos.
    const NUMERIC_MAX_FALLBACK = 99999999.99;

    function getFieldMax(input) {
        const parsed = parseFloat(input && input.max);
        return isNaN(parsed) ? NUMERIC_MAX_FALLBACK : parsed;
    }

    function getFieldMaxLabel(input) {
        if (input && input.dataset.maxLabel) return input.dataset.maxLabel;
        return getFieldMax(input).toLocaleString('es-VE', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    // ---------------------------------------------------------------------
    // FORMATEO NUMÉRICO EN VIVO (miles con punto, decimales con coma)
    // ---------------------------------------------------------------------
    function normalizeNumericString(raw) {
        let s = String(raw == null ? '' : raw)
            .replace(/\s|\u00a0/g, '')
            .replace(/[^\d.,-]/g, '');
        if (!s) return '';
        s = s.replace(/-/g, '');

        if (s.includes(',') && s.includes('.')) {
            if (s.lastIndexOf(',') > s.lastIndexOf('.')) {
                return s.replace(/\./g, '').replace(',', '.');
            }
            return s.replace(/,/g, '');
        }
        if (s.includes(',')) {
            const parts = s.split(',');
            if (parts.length === 2 && parts[1].length > 0 && parts[1].length <= 2) {
                return parts[0] + '.' + parts[1];
            }
            return s.replace(/,/g, '');
        }
        if ((s.match(/\./g) || []).length > 1) {
            const idx = s.lastIndexOf('.');
            const integerPart = s.slice(0, idx);
            const decimalPart = s.slice(idx + 1);
            if (decimalPart.length === 2 && integerPart) {
                return integerPart.replace(/\./g, '') + '.' + decimalPart;
            }
            return s.replace(/\./g, '');
        }
        return s;
    }

    function parseLocalizedNumber(raw) {
        const normalized = normalizeNumericString(raw);
        if (!normalized) return NaN;
        return parseFloat(normalized);
    }

    function formatNumericInput(raw, forceDecimals) {
        const normalized = normalizeNumericString(raw);
        if (!normalized) return '';

        const value = parseFloat(normalized);
        if (!Number.isFinite(value)) return '';

        const hasDecimalPoint = normalized.includes('.');
        let [integerDigits, decimalDigits] = normalized.split('.');
        integerDigits = (integerDigits || '0').replace(/^0+(?=\d)/, '');
        decimalDigits = (decimalDigits || '').replace(/\D/g, '').slice(0, 2);

        const grouped = integerDigits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        if (forceDecimals) {
            return grouped + ',' + (decimalDigits + '00').slice(0, 2);
        }
        if (hasDecimalPoint) {
            return grouped + ',' + decimalDigits;
        }
        return grouped;
    }

    function applyNumericFormat(input, forceDecimals) {
        if (!input) return;
        const previous = input.value;
        const caret = input.selectionStart == null ? previous.length : input.selectionStart;
        const digitsToRight = previous.slice(caret).replace(/\D/g, '').length;

        const formatted = formatNumericInput(previous, forceDecimals);
        if (formatted === previous) return;
        input.value = formatted;

        // Conserva el cursor contando dígitos a la derecha, no caracteres.
        let position = formatted.length;
        let remaining = digitsToRight;
        while (position > 0 && remaining > 0) {
            position -= 1;
            if (/\d/.test(formatted[position])) remaining -= 1;
        }
        input.setSelectionRange(position, position);
    }

    function showFormAlert(message) {
        clearFormAlert();
        if (!mainForm || !mainForm.parentNode) return;
        const alert = document.createElement('div');
        alert.className = 'alert-error js-form-alert';
        alert.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i>';
        alert.appendChild(document.createTextNode(message));
        mainForm.parentNode.insertBefore(alert, mainForm);
        alert.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function clearFormAlert() {
        const existingAlert = document.querySelector('.js-form-alert');
        if (existingAlert) existingAlert.remove();
    }

    // Devuelve true si es válido, false si hay error y 'out_of_range' si
    // supera el máximo de la columna NUMERIC(10, 2).
    function validateDecimalInput(input, label) {
        if (!input) return true;
        const raw = input.value.trim();
        if (raw === '') {
            showFieldError(input, label + ' es obligatorio.');
            return false;
        }
        const value = parseLocalizedNumber(raw);
        if (!Number.isFinite(value)) {
            showFieldError(input, label + ' debe ser un número válido.');
            return false;
        }
        if (value < 0) {
            showFieldError(input, label + ' no puede ser negativo.');
            return false;
        }
        if (value > getFieldMax(input)) {
            showFieldError(input, label + ' no puede superar ' + getFieldMaxLabel(input) + '.');
            return 'out_of_range';
        }
        clearFieldError(input);
        return true;
    }

    function validateWasteLimit() {
        return validateDecimalInput(wasteLimitInput, 'El límite de merma');
    }

    function validateMinStock() {
        return validateDecimalInput(minStockInput, 'El mínimo de stock');
    }

    if (nameInput) {
        nameInput.addEventListener('blur', validateName);
        nameInput.addEventListener('blur', checkNameAvailability);
        nameInput.addEventListener('input', () => {
            if (nameInput.value.trim()) clearFieldError(nameInput);
            // Al cambiar el texto se libera el botón y se revalida con debounce.
            if (nameAlreadyExists) setNameExists(false);
            scheduleNameCheck();
        });
    }
    if (productTypeSelect) productTypeSelect.addEventListener('change', validateProductType);
    if (unitSelect) unitSelect.addEventListener('change', validateUnit);
    if (unitCustomInput) unitCustomInput.addEventListener('input', () => { if (unitCustomInput.value.trim()) clearFieldError(unitCustomInput); });
    if (skuInput) {
        skuInput.addEventListener('blur', validateSKU);
        skuInput.addEventListener('input', () => { if (skuInput.value.trim()) clearFieldError(skuInput); });
    }
    function bindNumericInput(input, validateFn) {
        if (!input) return;
        input.addEventListener('input', () => {
            clearFormAlert();
            applyNumericFormat(input, false);
            if (input.value.trim()) clearFieldError(input);
        });
        input.addEventListener('blur', () => {
            applyNumericFormat(input, true);
            validateFn();
        });
        // En modo edición los valores existentes se muestran ya formateados.
        if (input.value.trim()) {
            input.value = formatNumericInput(input.value, true);
        }
    }

    bindNumericInput(wasteLimitInput, validateWasteLimit);
    bindNumericInput(minStockInput, validateMinStock);

    if (mainForm) {
        mainForm.addEventListener('submit', (e) => {
            if (nameAlreadyExists) {
                e.preventDefault();
                setNameExists(true);
                nameInput.focus();
                nameInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }

            const isNameValid = validateName();
            const isTypeValid = validateProductType();
            const isUnitValid = validateUnit();
            const isSkuValid = validateSKU();
            const isWasteLimitValid = validateWasteLimit();
            const isMinStockValid = validateMinStock();

            const hasRangeError = isWasteLimitValid === 'out_of_range' || isMinStockValid === 'out_of_range';
            if (hasRangeError) {
                showFormAlert('Los valores de límite de merma y mínimo de stock no pueden superar ' +
                    getFieldMaxLabel(minStockInput || wasteLimitInput) + '. Revise los campos marcados.');
            }

            if (!isNameValid || !isTypeValid || !isUnitValid || !isSkuValid ||
                !isWasteLimitValid || !isMinStockValid) {
                e.preventDefault();
                const firstError = document.querySelector('.js-validation-error');
                if (firstError && !hasRangeError) {
                    firstError.parentNode.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                return;
            }

            // Al enviar se quita el formato visual: el backend recibe "1250.50".
            [wasteLimitInput, minStockInput].forEach((input) => {
                if (!input || !input.value.trim()) return;
                const parsed = parseLocalizedNumber(input.value);
                if (Number.isFinite(parsed)) {
                    input.value = parsed.toFixed(2);
                }
            });
        });
    }

    // =========================================================================
    // 3. LÓGICA DE UNIDAD DE MEDIDA Y ALTA RÁPIDA DE CATEGORÍA
    // =========================================================================
    // El insumo solo se vincula a la categoría: la regla de vencimiento vive
    // exclusivamente en la categoría, no en el producto.
    if (productTypeSelect) {
        productTypeSelect.addEventListener('change', (e) => {
            const val = e.target.value;
            if (val === '__ADD_NEW__') {
                openModal();
                productTypeSelect.value = lastSelectedProductType;
            } else {
                lastSelectedProductType = val;
            }
        });
    }

    function handleUnitSelectChange() {
        if (!unitSelect || !unitCustomInput) return;
        if (unitSelect.value === 'OTHER') {
            unitCustomInput.style.display = 'block';
        } else {
            unitCustomInput.style.display = 'none';
            clearFieldError(unitCustomInput);
        }
    }

    function initUnitOfMeasure() {
        if (!unitSelect) return;
        const selectedUnit = unitSelect.dataset.selected;
        if (selectedUnit) {
            const standardUnits = ['KG', 'LT', 'UN'];
            if (standardUnits.includes(selectedUnit)) {
                unitSelect.value = selectedUnit;
            } else if (selectedUnit.trim() !== '') {
                unitSelect.value = 'OTHER';
                unitCustomInput.value = selectedUnit;
            }
        }
        handleUnitSelectChange();
    }

    if (unitSelect) {
        unitSelect.addEventListener('change', handleUnitSelectChange);
        initUnitOfMeasure();
    }

    // =========================================================================
    // 4. LÓGICA Y VALIDACIÓN EN TIEMPO REAL DEL MODAL DE CATEGORÍA
    // =========================================================================
    function getModalExpirationControl() {
        const checked = document.querySelector('#quickCategoryForm input[name="expiration_control"]:checked');
        return checked ? checked.value : '';
    }

    function toggleModalShelfLife() {
        if (!modalShelfLifeContainer || !modalShelfLifeInput) return;
        if (getModalExpirationControl() === 'days') {
            modalShelfLifeContainer.style.display = 'flex';
            modalShelfLifeInput.disabled = false;
            modalShelfLifeInput.setAttribute('required', 'required');
        } else {
            modalShelfLifeContainer.style.display = 'none';
            modalShelfLifeInput.value = '';
            modalShelfLifeInput.disabled = true;
            modalShelfLifeInput.removeAttribute('required');
            clearModalShelfLifeError();
        }
    }

    function showModalExpirationError(msg) {
        if (modalExpirationError) {
            modalExpirationError.textContent = msg;
            modalExpirationError.style.display = 'block';
        }
    }

    function clearModalExpirationError() {
        if (modalExpirationError) modalExpirationError.style.display = 'none';
    }

    function showModalShelfLifeError(msg) {
        if (modalShelfLifeError) {
            modalShelfLifeError.textContent = msg;
            modalShelfLifeError.style.display = 'block';
        }
        if (modalShelfLifeInput) modalShelfLifeInput.style.borderColor = '#d62300';
    }

    function clearModalShelfLifeError() {
        if (modalShelfLifeError) modalShelfLifeError.style.display = 'none';
        if (modalShelfLifeInput) modalShelfLifeInput.style.borderColor = '';
    }

    function validateModalExpirationControl() {
        const control = getModalExpirationControl();
        clearModalExpirationError();

        if (!control) {
            showModalExpirationError('Debe seleccionar la regla de vencimiento: fecha manual en compra o días de vida útil.');
            return false;
        }

        if (control === 'days') {
            clearModalShelfLifeError();
            const raw = modalShelfLifeInput ? modalShelfLifeInput.value.trim() : '';
            const days = Number(raw);
            if (!raw || !Number.isInteger(days) || days < 1 || days > 365) {
                showModalShelfLifeError('Indique los días de vida útil: un número entero entre 1 y 365.');
                return false;
            }
        }
        return true;
    }

    modalExpirationRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
            clearModalExpirationError();
            toggleModalShelfLife();
        });
    });

    if (modalShelfLifeInput) {
        modalShelfLifeInput.addEventListener('input', () => {
            if (modalShelfLifeInput.value.trim()) clearModalShelfLifeError();
        });
    }

    function openModal() {
        modalOverlay.style.display = 'flex';
        modalErrorBox.style.display = 'none';
        clearModalCatNameError();
        clearModalExpirationError();
        clearModalShelfLifeError();
        toggleModalShelfLife();
        if (modalCatNameInput) modalCatNameInput.focus();
    }

    function closeModal() {
        modalOverlay.style.display = 'none';
        if (quickCategoryForm) quickCategoryForm.reset();
        toggleModalShelfLife();
        clearModalCatNameError();
        clearModalExpirationError();
        clearModalShelfLifeError();
        modalErrorBox.style.display = 'none';
    }

    if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);
    if (btnCancelModal) btnCancelModal.addEventListener('click', closeModal);
    if (modalOverlay) {
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) closeModal();
        });
    }

    function showModalCatNameError(msg) {
        if (catNameError) {
            catNameError.textContent = msg;
            catNameError.style.display = 'block';
        }
        if (modalCatNameInput) modalCatNameInput.style.borderColor = '#d62300';
    }

    function clearModalCatNameError() {
        if (catNameError) catNameError.style.display = 'none';
        if (modalCatNameInput) modalCatNameInput.style.borderColor = '';
    }

    // Validar si está vacío O si es duplicado (INSENSIBLE A TILDES, MAYÚSCULAS Y REPETICIONES)
    function validateModalCategoryName() {
        if (!modalCatNameInput) return false;
        const rawVal = modalCatNameInput.value.trim();

        if (!rawVal) {
            showModalCatNameError('El nombre de la categoría es obligatorio.');
            return false;
        }

        const normalizedVal = normalizeText(rawVal);
        const existingOptions = Array.from(productTypeSelect.options)
            .filter(opt => opt.value && opt.value !== '__ADD_NEW__')
            .map(opt => ({ raw: opt.textContent, norm: normalizeText(opt.textContent) }));

        const match = existingOptions.find(opt => opt.norm === normalizedVal);

        if (match) {
            showModalCatNameError(`La categoría "${match.raw}" ya se encuentra registrada.`);
            return false;
        }

        clearModalCatNameError();
        return true;
    }

    if (modalCatNameInput) {
        modalCatNameInput.addEventListener('input', validateModalCategoryName);
        modalCatNameInput.addEventListener('blur', validateModalCategoryName);
    }

    // Guardado por AJAX
    if (quickCategoryForm) {
        quickCategoryForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const nameOk = validateModalCategoryName();
            const expirationOk = validateModalExpirationControl();
            if (!nameOk || !expirationOk) {
                return;
            }

            const catNameValue = modalCatNameInput.value.trim();
            const payload = {
                name: catNameValue,
                expiration_control: getModalExpirationControl(),
                shelf_life_days: modalShelfLifeInput.value || ''
            };

            const API_URL = quickCategoryForm.dataset.apiUrl || '/inventory/categories/api/create';

            try {
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    const cat = result.category;

                    const newOption = document.createElement('option');
                    newOption.value = cat.id;
                    newOption.textContent = cat.name;
                    newOption.dataset.manual = cat.requires_manual_date ? 'true' : 'false';
                    newOption.dataset.days = cat.shelf_life_days;

                    const addNewOption = productTypeSelect.querySelector('option[value="__ADD_NEW__"]');
                    productTypeSelect.insertBefore(newOption, addNewOption);

                    productTypeSelect.value = cat.id;
                    lastSelectedProductType = cat.id;
                    clearFieldError(productTypeSelect);

                    closeModal();
                } else {
                    if (result.error) {
                        showModalCatNameError(result.error);
                    } else if (modalErrorBox) {
                        modalErrorBox.textContent = 'Error al guardar la categoría.';
                        modalErrorBox.style.display = 'block';
                    }
                }
            } catch (err) {
                console.error('Excepción Fetch:', err);
                if (modalErrorBox) {
                    modalErrorBox.textContent = 'Ocurrió un error de comunicación con el servidor.';
                    modalErrorBox.style.display = 'block';
                }
            }
        });
    }
});