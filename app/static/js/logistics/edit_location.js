document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('editLocationForm');
    if (!form) return;

    // 1. Extraer URLs y estados desde los atributos data-* del HTML (Adiós Jinja en JS)
    const checkNameUrl = form.getAttribute('data-check-name-url');
    const checkPhoneUrl = form.getAttribute('data-check-phone-url');
    const redirectUrl = form.getAttribute('data-redirect-url');
    const isSuccess = form.getAttribute('data-success') === 'true';

    // 2. Mostrar Modal de Éxito Premium y Redirección tras actualización
    if (isSuccess && redirectUrl) {
        const successModal = document.getElementById('successModal');
        if (successModal) {
            successModal.classList.add('show');
        }

        // Ejecutamos la redirección cuando la barra de carga finalice (3.5 segundos)
        setTimeout(function() {
            window.location.href = redirectUrl;
        }, 3500);
    }

    // 3. Captura de todos los campos del formulario
    const nameInput = document.querySelector('input[name="name"]');
    const phoneInput = document.querySelector('input[name="phone"]');
    const stateInput = document.querySelector('select[name="state"]');
    const addressInput = document.querySelector('textarea[name="address"]');
    const locationIdField = document.querySelector('input[name="location_id"]');
    const locId = locationIdField ? locationIdField.value : 0;

    let nameTimeout = null;
    let phoneTimeout = null;

    // --- VALIDACIÓN DE NOMBRE (Tiempo real + Duplicados con Debounce) ---
    if (nameInput) {
        nameInput.addEventListener('input', function() {
            clearTimeout(nameTimeout);
            const val = this.value.trim();
            
            const regex = /^[a-zA-Z0-9 áéíóúÁÉÍÓÚñÑüÜ.]*$/;
            if (val && !regex.test(val)) {
                marcarError(this, "El nombre contiene caracteres inválidos.");
                return; 
            }

            nameTimeout = setTimeout(async () => {
                if (val.length < 3) return;
                try {
                    const response = await fetch(checkNameUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: val, location_id: locId})
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(nameInput, "Esta sede ya existe.");
                    } else {
                        marcarExito(nameInput);
                    }
                } catch (e) {
                    console.error("Error validando nombre:", e);
                }
            }, 500);
        });
    }

    // --- VALIDACIÓN DE TELÉFONO (Formato + Duplicados con Debounce) ---
    if (phoneInput) {
        phoneInput.addEventListener('input', function() {
            clearTimeout(phoneTimeout);
            const val = this.value.trim();
            const pattern = /^(0414|0424|0412|0416|0426|0212)\d{7}$/;

            if (val && !pattern.test(val)) {
                marcarError(this, "Formato telefónico inválido.");
                return;
            }

            phoneTimeout = setTimeout(async () => {
                if (val.length < 11) return; 
                try {
                    const response = await fetch(checkPhoneUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone: val, location_id: locId})
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(phoneInput, "Este número ya está asignado a otra sede.");
                    } else {
                        marcarExito(phoneInput);
                    }
                } catch (e) {
                    console.error("Error validando teléfono:", e);
                }
            }, 500);
        });
    }

    // --- VALIDACIÓN INTERACTIVA AL SELECCIONAR/ESCRIBIR ---
    if (stateInput) {
        stateInput.addEventListener('change', function() {
            const val = this.value;
            if (val && !val.includes("Seleccione") && val !== "") {
                marcarExito(this);
            } else {
                marcarError(this, "Debe seleccionar un estado.");
            }
        });
    }

    if (addressInput) {
        addressInput.addEventListener('input', function() {
            if (this.value.trim().length > 0) {
                marcarExito(this);
            } else {
                marcarError(this, "La dirección detallada es obligatoria.");
            }
        });
    }

    // --- DETECTOR GLOBAL DE ENVÍO (Previene guardado con errores) ---
    form.addEventListener('submit', function(e) {
        let isFormValid = true;

        // 1. Validar Nombre Sede
        if (nameInput) {
            const nameVal = nameInput.value.trim();
            if (!nameVal) {
                marcarError(nameInput, "El nombre de la sede es obligatorio.");
                isFormValid = false;
            } else if (nameInput.classList.contains('is-invalid')) {
                isFormValid = false;
            }
        }

        // 2. Validar Estado
        if (stateInput) {
            const stateVal = stateInput.value;
            if (!stateVal || stateVal === "" || stateVal.includes("Seleccione")) {
                marcarError(stateInput, "Debe seleccionar un estado.");
                isFormValid = false;
            }
        }

        // 3. Validar Dirección Detallada
        if (addressInput) {
            const addressVal = addressInput.value.trim();
            if (!addressVal) {
                marcarError(addressInput, "La dirección detallada es obligatoria.");
                isFormValid = false;
            }
        }

        // 4. Validar Teléfono
        if (phoneInput) {
            const phoneVal = phoneInput.phoneVal || phoneInput.value.trim();
            if (!phoneVal) {
                marcarError(phoneInput, "El número de teléfono es obligatorio.");
                isFormValid = false;
            } else if (phoneInput.classList.contains('is-invalid')) {
                isFormValid = false;
            }
        }

        // Si hay algún campo inválido, bloqueamos el envío y hacemos foco con scroll suave
        if (!isFormValid) {
            e.preventDefault();
            
            const firstInvalidElement = form.querySelector('.is-invalid');
            if (firstInvalidElement) {
                firstInvalidElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                firstInvalidElement.focus();
            }
        }
    });

    // --- FUNCIONES DE UTILIDAD (Inyección de Clases Premium) ---
    function marcarError(el, msg) {
        el.classList.add('is-invalid');
        el.classList.remove('is-valid');
        let feedback = el.parentNode.querySelector('.invalid-feedback');
        if (!feedback) {
            feedback = document.createElement('div');
            feedback.className = 'invalid-feedback error-feedback-premium';
            el.parentNode.appendChild(feedback);
        }
        feedback.textContent = msg;
    }

    function marcarExito(el) {
        el.classList.remove('is-invalid');
        el.classList.add('is-valid');
        const feedback = el.parentNode.querySelector('.invalid-feedback');
        if (feedback) {
            feedback.remove();
        }
    }
});