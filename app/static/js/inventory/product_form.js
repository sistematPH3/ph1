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

    // Fechas y avisos
    const expirationDateGroup = document.getElementById('expiration-date-group');
    const dayInput = document.querySelector('input[name="date_day"]');
    const monthInput = document.querySelector('input[name="date_month"]');
    const yearInput = document.querySelector('input[name="date_year"]');
    const manualDateNotice = document.getElementById('manual-date-notice');
    const autoDateNotice = document.getElementById('auto-date-notice');
    const noticeDaysCount = document.getElementById('notice-days-count');

    // Elementos del Modal de Categoría
    const modalOverlay = document.getElementById('categoryModalOverlay');
    const btnCloseModal = document.getElementById('btnCloseCategoryModal');
    const btnCancelModal = document.getElementById('btnCancelCategoryModal');
    const quickCategoryForm = document.getElementById('quickCategoryForm');
    const modalErrorBox = document.getElementById('modalCategoryError');
    const modalCatNameInput = document.getElementById('modal_cat_name');
    const catNameError = document.getElementById('modal_cat_name_error');

    const modalRequiresManual = document.getElementById('modal_requires_manual_date');
    const modalHasShelfLife = document.getElementById('modal_has_shelf_life');
    const modalShelfLifeContainer = document.getElementById('modal_shelf_life_days_container');
    const modalShelfLifeInput = document.getElementById('modal_shelf_life_days');

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

        if (inputElement.name && inputElement.name.startsWith('date_')) {
            const dateContainer = expirationDateGroup;
            if (!dateContainer.querySelector('.js-validation-error')) {
                dateContainer.appendChild(errorSpan);
            }
        } else {
            inputElement.parentNode.appendChild(errorSpan);
        }

        inputElement.style.borderColor = '#d62300';
    }

    function clearFieldError(inputElement) {
        if (!inputElement) return;
        inputElement.style.borderColor = '';
        if (inputElement.name && inputElement.name.startsWith('date_')) {
            const existingError = expirationDateGroup.querySelector('.js-validation-error');
            if (existingError) existingError.remove();
        } else {
            const existingError = inputElement.parentNode.querySelector('.js-validation-error');
            if (existingError) existingError.remove();
        }
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

    function validatePrimaryExpirationDate() {
        if (expirationDateGroup && expirationDateGroup.style.display !== 'none') {
            const day = parseInt(dayInput.value, 10);
            const month = parseInt(monthInput.value, 10);
            const year = parseInt(yearInput.value, 10);

            if (!day || day < 1 || day > 31 || !month || month < 1 || month > 12 || !year || year < 2026) {
                showFieldError(dayInput, 'Ingrese una fecha de vencimiento válida (DD/MM/AAAA).');
                return false;
            }
        }
        clearFieldError(dayInput);
        return true;
    }

    if (nameInput) {
        nameInput.addEventListener('blur', validateName);
        nameInput.addEventListener('input', () => { if (nameInput.value.trim()) clearFieldError(nameInput); });
    }
    if (productTypeSelect) productTypeSelect.addEventListener('change', validateProductType);
    if (unitSelect) unitSelect.addEventListener('change', validateUnit);
    if (unitCustomInput) unitCustomInput.addEventListener('input', () => { if (unitCustomInput.value.trim()) clearFieldError(unitCustomInput); });
    if (skuInput) {
        skuInput.addEventListener('blur', validateSKU);
        skuInput.addEventListener('input', () => { if (skuInput.value.trim()) clearFieldError(skuInput); });
    }

    [dayInput, monthInput, yearInput].forEach(input => {
        if (input) input.addEventListener('input', validatePrimaryExpirationDate);
    });

    if (mainForm) {
        mainForm.addEventListener('submit', (e) => {
            const isNameValid = validateName();
            const isTypeValid = validateProductType();
            const isUnitValid = validateUnit();
            const isSkuValid = validateSKU();
            const isDateValid = validatePrimaryExpirationDate();

            if (!isNameValid || !isTypeValid || !isUnitValid || !isSkuValid || !isDateValid) {
                e.preventDefault();
                const firstError = document.querySelector('.js-validation-error');
                if (firstError) {
                    firstError.parentNode.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        });
    }

    // =========================================================================
    // 3. LÓGICA DE AVISOS Y UNIDAD DE MEDIDA
    // =========================================================================
    function updateProductTypeUI() {
        if (!productTypeSelect) return;
        const selectedOption = productTypeSelect.options[productTypeSelect.selectedIndex];
        
        if (!selectedOption || !selectedOption.value || selectedOption.value === '__ADD_NEW__') {
            if (expirationDateGroup) expirationDateGroup.style.display = 'none';
            if (manualDateNotice) manualDateNotice.style.display = 'none';
            if (autoDateNotice) autoDateNotice.style.display = 'none';
            return;
        }

        const isManual = selectedOption.dataset.manual === 'true';
        const shelfLifeDays = parseInt(selectedOption.dataset.days || '0', 10);

        if (isManual) {
            if (manualDateNotice) manualDateNotice.style.display = 'block';
            if (autoDateNotice) autoDateNotice.style.display = 'none';
            if (expirationDateGroup) expirationDateGroup.style.display = 'none';
        } else if (shelfLifeDays > 0) {
            if (noticeDaysCount) noticeDaysCount.textContent = shelfLifeDays;
            if (autoDateNotice) autoDateNotice.style.display = 'block';
            if (manualDateNotice) manualDateNotice.style.display = 'none';
            if (expirationDateGroup) expirationDateGroup.style.display = 'none';
        } else {
            if (expirationDateGroup) expirationDateGroup.style.display = 'block';
            if (manualDateNotice) manualDateNotice.style.display = 'none';
            if (autoDateNotice) autoDateNotice.style.display = 'none';
        }
    }

    if (productTypeSelect) {
        productTypeSelect.addEventListener('change', (e) => {
            const val = e.target.value;
            if (val === '__ADD_NEW__') {
                openModal();
                productTypeSelect.value = lastSelectedProductType;
            } else {
                lastSelectedProductType = val;
                updateProductTypeUI();
            }
        });
        updateProductTypeUI();
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
    function toggleModalShelfLife() {
        if (modalHasShelfLife.checked) {
            modalShelfLifeContainer.style.display = 'flex';
            if (modalShelfLifeInput.value === '0') modalShelfLifeInput.value = '';
            modalRequiresManual.checked = false;
        } else {
            modalShelfLifeContainer.style.display = 'none';
            modalShelfLifeInput.value = 0;
        }
    }

    if (modalRequiresManual && modalHasShelfLife) {
        modalRequiresManual.addEventListener('change', () => {
            if (modalRequiresManual.checked) {
                modalHasShelfLife.checked = false;
                toggleModalShelfLife();
            }
        });
        modalHasShelfLife.addEventListener('change', toggleModalShelfLife);
    }

    function openModal() {
        modalOverlay.style.display = 'flex';
        modalErrorBox.style.display = 'none';
        clearModalCatNameError();
        if (modalCatNameInput) modalCatNameInput.focus();
    }

    function closeModal() {
        modalOverlay.style.display = 'none';
        if (quickCategoryForm) quickCategoryForm.reset();
        toggleModalShelfLife();
        clearModalCatNameError();
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

            if (!validateModalCategoryName()) {
                return;
            }

            const catNameValue = modalCatNameInput.value.trim();
            const payload = {
                name: catNameValue,
                requires_manual_date: modalRequiresManual.checked ? "true" : "",
                shelf_life_days: modalShelfLifeInput.value || 0
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
                    updateProductTypeUI();

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