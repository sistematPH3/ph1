// static/js/inventory/category_form.js

document.addEventListener('DOMContentLoaded', () => {
    const hasShelfLifeCheckbox = document.getElementById('has_shelf_life');
    const shelfLifeDaysContainer = document.getElementById('shelf_life_days_container');
    const shelfLifeDaysInput = document.getElementById('shelf_life_days');
    const requiresManualCheckbox = document.getElementById('requires_manual_date');

    function toggleShelfLifeInput() {
        if (hasShelfLifeCheckbox.checked) {
            shelfLifeDaysContainer.style.display = 'flex';
            if(shelfLifeDaysInput.value == 0) shelfLifeDaysInput.value = '';
            shelfLifeDaysInput.setAttribute('required', 'required');
            requiresManualCheckbox.checked = false; 
        } else {
            shelfLifeDaysContainer.style.display = 'none';
            shelfLifeDaysInput.removeAttribute('required');
            shelfLifeDaysInput.value = 0;
        }
    }

    if (requiresManualCheckbox && hasShelfLifeCheckbox) {
        requiresManualCheckbox.addEventListener('change', () => {
            if(requiresManualCheckbox.checked) {
                hasShelfLifeCheckbox.checked = false;
                toggleShelfLifeInput();
            }
        });

        hasShelfLifeCheckbox.addEventListener('change', toggleShelfLifeInput);
        
        // Ejecución inicial por si estás editando y ya vienen datos
        toggleShelfLifeInput();
    }
});