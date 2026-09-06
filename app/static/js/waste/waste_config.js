document.addEventListener('DOMContentLoaded', () => {

    const inputTolerance = document.getElementById('WASTE_TIME_TOLERANCE');
    const sliderTolerance = document.getElementById('slider-tolerance');
    const btnDecrementTolerance = document.getElementById('btn-decrement-tolerance');
    const btnIncrementTolerance = document.getElementById('btn-increment-tolerance');
    const previewPercentVal = document.getElementById('preview-percent-val');
    const previewResultVal = document.getElementById('preview-result-val');
    const errorTolerance = document.getElementById('error-tolerance');

    const inputDays = document.getElementById('WASTE_BASE_PERIOD_DAYS');
    const sliderDays = document.getElementById('slider-days');
    const previewDaysVal = document.getElementById('preview-days-val');
    const errorDays = document.getElementById('error-days');

    /* =========================================================================
       1. VISTA PREVIA Y SIMULACIÓN DE TOLERANCIA (sin unidades, sin tope)
       ========================================================================= */
    function updateToleranceSimulation(val) {
        const raw = parseFloat(val);
        const invalid = isNaN(raw) || raw < 1.0;
        const marginVal = invalid ? 1.0 : raw;

        // Porcentaje adicional: Si es 1.50 -> +50% | Si es 1.00 -> +0%
        const percentExtra = Math.round((marginVal - 1.0) * 100);

        // Simulación relativa con base de 10: 10 * 1.50 = 15.0
        const resultVal = (10 * marginVal).toFixed(1);

        if (previewPercentVal) previewPercentVal.textContent = `+${percentExtra}%`;
        if (previewResultVal) previewResultVal.textContent = `${resultVal}`;
        if (errorTolerance) errorTolerance.classList.toggle('d-none', !invalid);
    }

    function updateDaysSimulation(val) {
        const intVal = parseInt(val, 10);
        const invalid = isNaN(intVal) || intVal < 1 || intVal > 90;
        if (!invalid && previewDaysVal) previewDaysVal.textContent = intVal;
        if (errorDays) errorDays.classList.toggle('d-none', !invalid);
    }

    /* =========================================================================
       2. CONTROL DE TOLERANCIA (MÍNIMO 1.00, SIN MÁXIMO FIJO)
       ========================================================================= */
    if (inputTolerance) {

        // Bloquear caracteres de notación científica ('e', 'E', '+', '-')
        inputTolerance.addEventListener('keydown', (e) => {
            if (['e', 'E', '+', '-'].includes(e.key)) {
                e.preventDefault();
            }
        });

        inputTolerance.addEventListener('input', (e) => {
            let valStr = e.target.value;

            // Si está vacío, mostramos simulación base en 1.00
            if (valStr === '') {
                updateToleranceSimulation(1.0);
                return;
            }

            // Máximo 2 decimales mientras escribe
            if (valStr.includes('.')) {
                const parts = valStr.split('.');
                if (parts[1].length > 2) {
                    valStr = `${parts[0]}.${parts[1].slice(0, 2)}`;
                    e.target.value = valStr;
                }
            }

            const val = parseFloat(valStr);

            // No sobreescribimos el valor inválido mientras escribe:
            // la simulación muestra la advertencia de inmediato.
            if (sliderTolerance && !(isNaN(val) || val < 1.0)) {
                sliderTolerance.value = val;
            }
            updateToleranceSimulation(val);
        });

        // Al perder el foco (blur), formatear a 2 decimales limpios
        inputTolerance.addEventListener('blur', (e) => {
            let val = parseFloat(e.target.value);

            if (isNaN(val) || val < 1.0) val = 1.0;

            e.target.value = val.toFixed(2);
            if (sliderTolerance) sliderTolerance.value = val.toFixed(2);
            updateToleranceSimulation(val);
        });

        if (sliderTolerance) {
            sliderTolerance.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value) || 1.0;
                inputTolerance.value = val.toFixed(2);
                updateToleranceSimulation(val);
            });
        }

        if (btnDecrementTolerance) {
            btnDecrementTolerance.addEventListener('click', () => {
                let current = parseFloat(inputTolerance.value) || 1.0;
                current = Math.max(1.00, current - 0.05);
                inputTolerance.value = current.toFixed(2);
                if (sliderTolerance) sliderTolerance.value = current.toFixed(2);
                updateToleranceSimulation(current);
            });
        }

        if (btnIncrementTolerance) {
            btnIncrementTolerance.addEventListener('click', () => {
                let current = parseFloat(inputTolerance.value) || 1.0;
                current += 0.05; // Sin tope superior
                inputTolerance.value = current.toFixed(2);
                if (sliderTolerance) sliderTolerance.value = current.toFixed(2);
                updateToleranceSimulation(current);
            });
        }
    }

    /* =========================================================================
       3. CONTROL DE DÍAS (MÍNIMO 1, MÁXIMO 90)
       ========================================================================= */
    if (inputDays && sliderDays) {

        inputDays.addEventListener('input', (e) => {
            const valStr = e.target.value;

            if (valStr === '') {
                updateDaysSimulation(1);
                return;
            }

            const val = parseInt(valStr, 10);
            const valid = !isNaN(val) && val >= 1 && val <= 90;

            // No sobreescribimos el valor inválido mientras escribe:
            // la simulación muestra la advertencia de inmediato.
            if (valid && sliderDays) sliderDays.value = val;
            updateDaysSimulation(val);
        });

        inputDays.addEventListener('blur', (e) => {
            let val = parseInt(e.target.value, 10);
            if (isNaN(val) || val < 1) val = 1;
            if (val > 90) val = 90;

            e.target.value = val;
            sliderDays.value = val;
            updateDaysSimulation(val);
        });

        sliderDays.addEventListener('input', (e) => {
            inputDays.value = e.target.value;
            updateDaysSimulation(e.target.value);
        });
    }

    // Inicialización inicial
    if (inputTolerance) updateToleranceSimulation(inputTolerance.value);
    if (inputDays) updateDaysSimulation(inputDays.value);

    /* =========================================================================
       4. ENVÍO DEL FORMULARIO Y MODAL
       ========================================================================= */
    const form = document.getElementById('form-waste-config');
    const modal = document.getElementById('success-modal');
    const btnAcceptModal = document.getElementById('btn-modal-accept');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData(form);

            try {
                const response = await fetch('/api/waste/merma/config', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    if (modal) modal.classList.add('show');
                } else {
                    alert(result.message || 'Error al guardar la configuración.');
                }
            } catch (error) {
                console.error('Error de red:', error);
                alert('Ocurrió un error al intentar conectar con el servidor.');
            }
        });
    }

    if (btnAcceptModal) {
        btnAcceptModal.addEventListener('click', () => {
            window.location.reload();
        });
    }
});