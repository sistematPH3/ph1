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
            if (!validateName()) {
                e.preventDefault(); // Detener envío si no es válido
                nameInput.focus();
            }
        });
    }

    // Lógica de switches/checkboxes de Días de Vida Útil
    const hasShelfLifeCheckbox = document.getElementById('has_shelf_life');
    const shelfLifeDaysContainer = document.getElementById('shelf_life_days_container');
    const shelfLifeDaysInput = document.getElementById('shelf_life_days');
    const requiresManualCheckbox = document.getElementById('requires_manual_date');

    function toggleShelfLifeInput() {
        if (!hasShelfLifeCheckbox || !shelfLifeDaysContainer) return;

        if (hasShelfLifeCheckbox.checked) {
            shelfLifeDaysContainer.style.display = 'flex';
            if (shelfLifeDaysInput.value == 0) shelfLifeDaysInput.value = '';
            shelfLifeDaysInput.setAttribute('required', 'required');
            if (requiresManualCheckbox) requiresManualCheckbox.checked = false; 
        } else {
            shelfLifeDaysContainer.style.display = 'none';
            shelfLifeDaysInput.removeAttribute('required');
            shelfLifeDaysInput.value = 0;
        }
    }

    if (requiresManualCheckbox && hasShelfLifeCheckbox) {
        requiresManualCheckbox.addEventListener('change', () => {
            if (requiresManualCheckbox.checked) {
                hasShelfLifeCheckbox.checked = false;
                toggleShelfLifeInput();
            }
        });

        hasShelfLifeCheckbox.addEventListener('change', toggleShelfLifeInput);
        toggleShelfLifeInput();
    }
});