// static/js/inventory/category_form.js

document.addEventListener('DOMContentLoaded', () => {
    const categoryForm = document.querySelector('form');
    const nameInput = document.getElementById('name');
    const nameErrorText = document.getElementById('name-error-text');

    // HELPER: NORMALIZAR TEXTO EN JS
    function normalizeText(text) {
        if (!text) return '';
        return text
            .trim()
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "") // Quitar tildes
            .replace(/(.)\1+/g, "$1")         // Colapsar letras repetidas ("aaaaa" -> "a")
            .replace(/(es|s)$/g, "");         // Quitar "s" o "es" final
    }

    // Muestra error debajo del input
    function showNameError(message) {
        if (nameErrorText) {
            nameErrorText.textContent = message;
            nameErrorText.classList.remove('d-none');
            nameErrorText.style.display = 'block';
        }
        if (nameInput) {
            nameInput.style.borderColor = '#d62300';
        }
    }

    // Oculta error
    function clearNameError() {
        if (nameErrorText) {
            nameErrorText.classList.add('d-none');
            nameErrorText.style.display = 'none';
        }
        if (nameInput) {
            nameInput.style.borderColor = '';
        }
    }

    // Validación en tiempo real (vacío + duplicados)
    function validateName() {
        if (!nameInput) return true;
        const val = nameInput.value.trim();

        if (!val) {
            showNameError('El nombre de la categoría es obligatorio.');
            return false;
        }

        // Obtener la lista de nombres desde el atributo data-existing
        let existingCategories = [];
        try {
            const rawAttr = categoryForm ? categoryForm.dataset.existing : '[]';
            existingCategories = JSON.parse(rawAttr || '[]');
        } catch (e) {
            console.error('Error procesando categorías existentes:', e);
        }

        const normalizedVal = normalizeText(val);
        const match = existingCategories.find(catName => normalizeText(catName) === normalizedVal);

        if (match) {
            showNameError(`La categoría "${match}" ya se encuentra registrada.`);
            return false;
        }

        clearNameError();
        return true;
    }

    if (nameInput) {
        nameInput.addEventListener('input', validateName);
        nameInput.addEventListener('blur', validateName);
    }

    if (categoryForm) {
        categoryForm.addEventListener('submit', (e) => {
            const nameOk = validateName();
            const expirationOk = validateExpirationControl();

            if (!nameOk || !expirationOk) {
                e.preventDefault(); // Detener envío si no es válido
                if (!nameOk && nameInput) {
                    nameInput.focus();
                } else if (!expirationOk) {
                    const firstRadio = document.querySelector('input[name="expiration_control"]');
                    if (firstRadio) firstRadio.focus();
                }
            }
        });
    }

    // -------------------------------------------------------------------------
    // REGLA DE VENCIMIENTO (OBLIGATORIA Y EXCLUYENTE) DE LA CATEGORÍA
    // -------------------------------------------------------------------------
    const expirationRadios = document.querySelectorAll('input[name="expiration_control"]');
    const shelfLifeDaysContainer = document.getElementById('shelf_life_days_container');
    const shelfLifeDaysInput = document.getElementById('shelf_life_days');
    const expirationControlError = document.getElementById('expiration-control-error');
    const shelfLifeDaysError = document.getElementById('shelf-life-days-error');

    function getSelectedExpirationControl() {
        const checked = document.querySelector('input[name="expiration_control"]:checked');
        return checked ? checked.value : '';
    }

    function showExpirationError(message) {
        if (expirationControlError) {
            expirationControlError.textContent = message;
            expirationControlError.classList.remove('d-none');
            expirationControlError.style.display = 'block';
        }
    }

    function clearExpirationError() {
        if (expirationControlError) {
            expirationControlError.classList.add('d-none');
            expirationControlError.style.display = 'none';
        }
    }

    function showShelfLifeDaysError(message) {
        if (shelfLifeDaysError) {
            shelfLifeDaysError.textContent = message;
            shelfLifeDaysError.classList.remove('d-none');
            shelfLifeDaysError.style.display = 'block';
        }
        if (shelfLifeDaysInput) shelfLifeDaysInput.style.borderColor = '#d62300';
    }

    function clearShelfLifeDaysError() {
        if (shelfLifeDaysError) {
            shelfLifeDaysError.classList.add('d-none');
            shelfLifeDaysError.style.display = 'none';
        }
        if (shelfLifeDaysInput) shelfLifeDaysInput.style.borderColor = '';
    }

    // El campo de días solo aplica con la regla 'days'.
    function toggleShelfLifeInput() {
        if (!shelfLifeDaysContainer || !shelfLifeDaysInput) return;

        if (getSelectedExpirationControl() === 'days') {
            shelfLifeDaysContainer.style.display = 'flex';
            shelfLifeDaysInput.disabled = false;
            shelfLifeDaysInput.setAttribute('required', 'required');
        } else {
            shelfLifeDaysContainer.style.display = 'none';
            shelfLifeDaysInput.value = '';
            shelfLifeDaysInput.disabled = true;
            shelfLifeDaysInput.removeAttribute('required');
            clearShelfLifeDaysError();
        }
    }

    function validateExpirationControl() {
        const control = getSelectedExpirationControl();
        let isValid = true;

        if (!control) {
            showExpirationError('Debe seleccionar la regla de vencimiento: fecha manual en compra o días de vida útil.');
            return false;
        }
        clearExpirationError();

        if (control === 'days') {
            const raw = shelfLifeDaysInput ? shelfLifeDaysInput.value.trim() : '';
            const days = Number(raw);
            if (!raw || !Number.isInteger(days) || days < 1 || days > 365) {
                showShelfLifeDaysError('Indique los días de vida útil: un número entero entre 1 y 365.');
                isValid = false;
            } else {
                clearShelfLifeDaysError();
            }
        } else {
            clearShelfLifeDaysError();
        }

        return isValid;
    }

    expirationRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
            clearExpirationError();
            toggleShelfLifeInput();
        });
    });

    if (shelfLifeDaysInput) {
        shelfLifeDaysInput.addEventListener('input', () => {
            if (shelfLifeDaysInput.value.trim()) clearShelfLifeDaysError();
        });
    }

    toggleShelfLifeInput();
});