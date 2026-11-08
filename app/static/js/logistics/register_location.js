document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('registerLocationForm');
    if (!form) return;

    const checkNameUrl = form.getAttribute('data-check-name-url');
    const checkPhoneUrl = form.getAttribute('data-check-phone-url');
    const redirectUrl = form.getAttribute('data-redirect-url');
    const isSuccess = form.getAttribute('data-success') === 'true';

    if (isSuccess && redirectUrl) {
        const successModal = document.getElementById('successModal');
        const btnAceptar = document.getElementById('btnAceptarSuccess');
        
        if (successModal) {
            successModal.classList.add('show');
        }

        if (btnAceptar) {
            btnAceptar.addEventListener('click', function() {
                window.location.href = redirectUrl;
            });
        }
    }

    const nameInput = document.querySelector('input[name="name"]');
    const phoneInput = document.querySelector('input[name="phone"]');
    const stateInput = document.querySelector('select[name="state"]'); 
    const addressInput = document.querySelector('textarea[name="address"]'); 
    const locationIdField = document.querySelector('input[name="location_id"]');
    const locId = locationIdField ? locationIdField.value : 0;

    let nameTimeout = null;
    let phoneTimeout = null;

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
                }
            }, 500);
        });
    }

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
                }
            }, 500);
        });
    }

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

    form.addEventListener('submit', function(e) {
        let isFormValid = true;

        if (nameInput) {
            const nameVal = nameInput.value.trim();
            if (!nameVal) {
                marcarError(nameInput, "El nombre de la sede es obligatorio.");
                isFormValid = false;
            } else if (nameInput.classList.contains('is-invalid')) {
                isFormValid = false;
            }
        }

        if (stateInput) {
            const stateVal = stateInput.value;
            if (!stateVal || stateVal === "" || stateVal.includes("Seleccione")) {
                marcarError(stateInput, "Debe seleccionar un estado.");
                isFormValid = false;
            }
        }

        if (addressInput) {
            const addressVal = addressInput.value.trim();
            if (!addressVal) {
                marcarError(addressInput, "La dirección detallada es obligatoria.");
                isFormValid = false;
            }
        }

        if (phoneInput) {
            const phoneVal = phoneInput.value.trim();
            if (!phoneVal) {
                marcarError(phoneInput, "El número de teléfono es obligatorio.");
                isFormValid = false;
            } else if (phoneInput.classList.contains('is-invalid')) {
                isFormValid = false;
            }
        }

        if (!isFormValid) {
            e.preventDefault();
            
            const firstInvalidElement = form.querySelector('.is-invalid');
            if (firstInvalidElement) {
                firstInvalidElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                firstInvalidElement.focus();
            }
        }
    });

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