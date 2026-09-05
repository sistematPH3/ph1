document.addEventListener('DOMContentLoaded', () => {

    const inputTolerance = document.getElementById('WASTE_TIME_TOLERANCE');
    const sliderTolerance = document.getElementById('slider-tolerance');
    const btnDecrementTolerance = document.getElementById('btn-decrement-tolerance');
    const btnIncrementTolerance = document.getElementById('btn-increment-tolerance');
    const previewPercentVal = document.getElementById('preview-percent-val');
    const previewResultVal = document.getElementById('preview-result-val');

    const inputDays = document.getElementById('WASTE_BASE_PERIOD_DAYS');
    const sliderDays = document.getElementById('slider-days');
    const previewDaysVal = document.getElementById('preview-days-val');

    /* =========================================================================
       1. VISTA PREVIA Y SIMULACIÓN DE TOLERANCIA
       ========================================================================= */
    function updateToleranceSimulation(val) {
        let marginVal = parseFloat(val);
        if (isNaN(marginVal) || marginVal < 1.0) marginVal = 1.0;
        if (marginVal > 3.0) marginVal = 3.0;

        // Porcentaje adicional: Si es 1.50 -> +50% | Si es 1.00 -> +0%
        const percentExtra = Math.round((marginVal - 1.0) * 100);
        
        // Simulación con base de 10 kg: 10 * 1.50 = 15.0 kg
        const resultVal = (10 * marginVal).toFixed(1);

        if (previewPercentVal) previewPercentVal.textContent = `+${percentExtra}%`;
        if (previewResultVal) previewResultVal.textContent = `${resultVal} kg`;
    }

    function updateDaysSimulation(val) {
        const intVal = parseInt(val, 10) || 1;
        if (previewDaysVal) previewDaysVal.textContent = intVal;
    }

    /* =========================================================================
       2. CONTROL DE TOLERANCIA (MÍNIMO 1.00, MÁXIMO 3.00)
       ========================================================================= */
    if (inputTolerance && sliderTolerance) {

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

            let val = parseFloat(valStr);

            // Control de límites (Mínimo 1.00, Máximo 3.00)
            if (val > 3.0) {
                val = 3.0;
                e.target.value = '3.00';
            } else if (val < 1.0 || isNaN(val)) {
                val = 1.0;
            }

            sliderTolerance.value = val;
            updateToleranceSimulation(val);
        });

        // Al perder el foco (blur), formatear a 2 decimales limpios dentro del rango
        inputTolerance.addEventListener('blur', (e) => {
            let val = parseFloat(e.target.value);
            
            if (isNaN(val) || val < 1.0) val = 1.0;
            if (val > 3.0) val = 3.0;

            e.target.value = val.toFixed(2);
            sliderTolerance.value = val.toFixed(2);
            updateToleranceSimulation(val);
        });

        sliderTolerance.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value) || 1.0;
            inputTolerance.value = val.toFixed(2);
            updateToleranceSimulation(val);
        });

        if (btnDecrementTolerance) {
            btnDecrementTolerance.addEventListener('click', () => {
                let current = parseFloat(inputTolerance.value) || 1.0;
                current = Math.max(1.00, current - 0.05);
                inputTolerance.value = current.toFixed(2);
                sliderTolerance.value = current.toFixed(2);
                updateToleranceSimulation(current);
            });
        }

        if (btnIncrementTolerance) {
            btnIncrementTolerance.addEventListener('click', () => {
                let current = parseFloat(inputTolerance.value) || 1.0;
                current = Math.min(3.00, current + 0.05); // Limitado a 3.00
                inputTolerance.value = current.toFixed(2);
                sliderTolerance.value = current.toFixed(2);
                updateToleranceSimulation(current);
            });
        }
    }

    /* =========================================================================
       3. CONTROL DE DÍAS (MÍNIMO 1, MÁXIMO 90)
       ========================================================================= */
    if (inputDays && sliderDays) {

        inputDays.addEventListener('input', (e) => {
            let valStr = e.target.value;

            if (valStr === '') {
                updateDaysSimulation(1);
                return;
            }

            let val = parseInt(valStr, 10);

            if (val > 90) {
                e.target.value = 90;
                val = 90;
            } else if (val < 1 || isNaN(val)) {
                e.target.value = 1;
                val = 1;
            }

            sliderDays.value = val;
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