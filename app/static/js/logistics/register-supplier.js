document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('supplierForm');
    if (!form) return;

    const checkNameUrl = form.getAttribute('data-check-name-url');
    const checkPhoneUrl = form.getAttribute('data-check-phone-url');
    const checkTaxIdUrl = form.getAttribute('data-check-tax-id-url');
    const checkEmailUrl = form.getAttribute('data-check-email-url');
    const supId = form.getAttribute('data-supplier-id') || 0;

    const nameInput = document.getElementById('name');
    const taxIdInput = document.getElementById('tax_id');
    const phoneInput = document.getElementById('phone');
    const emailInput = document.getElementById('email');

    let nameTimeout = null;
    let taxIdTimeout = null;
    let phoneTimeout = null;
    let emailTimeout = null;

    if (nameInput) {
        nameInput.addEventListener('input', function() {
            clearTimeout(nameTimeout);
            const val = this.value.trim();

            if (!val) {
                marcarError(this, "El nombre o razón social es obligatorio.");
                return;
            }

            nameTimeout = setTimeout(async () => {
                if (val.length < 3) return;
                try {
                    const response = await fetch(checkNameUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: val, supplier_id: supId })
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(nameInput, "Ya existe un proveedor con este nombre.");
                    } else {
                        marcarExito(nameInput);
                    }
                } catch (e) {}
            }, 500);
        });
    }

    if (taxIdInput) {
        taxIdInput.addEventListener('input', function() {
            clearTimeout(taxIdTimeout);
            const val = this.value.trim();

            if (!val) {
                marcarError(this, "El RIF / Tax ID es obligatorio.");
                return;
            }

            taxIdTimeout = setTimeout(async () => {
                try {
                    const response = await fetch(checkTaxIdUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ tax_id: val, supplier_id: supId })
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(taxIdInput, "Este RIF / Tax ID ya se encuentra registrado.");
                    } else {
                        marcarExito(taxIdInput);
                    }
                } catch (e) {}
            }, 500);
        });
    }

    if (phoneInput) {
        phoneInput.addEventListener('input', function() {
            clearTimeout(phoneTimeout);
            const val = this.value.trim();
            const pattern = /^\+?[0-9][0-9\-\s]{7,18}[0-9]$/;

            if (val && !pattern.test(val)) {
                marcarError(this, "Formato telefónico inválido. Ej: +58 412-0000000");
                return;
            }

            phoneTimeout = setTimeout(async () => {
                if (!val) return;
                try {
                    const response = await fetch(checkPhoneUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ phone: val, supplier_id: supId })
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(phoneInput, "Este número ya pertenece a otro proveedor.");
                    } else {
                        marcarExito(phoneInput);
                    }
                } catch (e) {}
            }, 500);
        });
    }

    if (emailInput) {
        const emailRegex = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
        emailInput.addEventListener('input', function() {
            clearTimeout(emailTimeout);
            const val = this.value.trim();

            if (val && !emailRegex.test(val)) {
                marcarError(this, "Formato de correo electrónico inválido.");
                return;
            }

            emailTimeout = setTimeout(async () => {
                if (!val) return;
                try {
                    const response = await fetch(checkEmailUrl, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ email: val, supplier_id: supId })
                    });
                    const data = await response.json();
                    if (!data.available) {
                        marcarError(emailInput, "Este correo ya pertenece a otro proveedor.");
                    } else {
                        marcarExito(emailInput);
                    }
                } catch (e) {}
            }, 500);
        });
    }

    form.addEventListener('submit', function(e) {
        let isFormValid = true;

        if (nameInput && (!nameInput.value.trim() || nameInput.classList.contains('is-invalid'))) {
            if (!nameInput.value.trim()) marcarError(nameInput, "El nombre es obligatorio.");
            isFormValid = false;
        }

        if (taxIdInput && (!taxIdInput.value.trim() || taxIdInput.classList.contains('is-invalid'))) {
            if (!taxIdInput.value.trim()) marcarError(taxIdInput, "El RIF / Tax ID es obligatorio.");
            isFormValid = false;
        }

        if (phoneInput && (!phoneInput.value.trim() || phoneInput.classList.contains('is-invalid'))) {
            if (!phoneInput.value.trim()) marcarError(phoneInput, "El teléfono es obligatorio.");
            isFormValid = false;
        }

        if (emailInput && emailInput.classList.contains('is-invalid')) {
            isFormValid = false;
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
        let feedback = el.parentNode.querySelector('.validation-msg, .invalid-feedback');
        if (!feedback) {
            feedback = document.createElement('small');
            feedback.className = 'validation-msg text-danger d-block mt-1';
            el.parentNode.appendChild(feedback);
        } else {
            feedback.className = 'validation-msg text-danger d-block mt-1';
        }
        feedback.textContent = msg;
    }

    function marcarExito(el) {
        el.classList.remove('is-invalid');
        el.classList.add('is-valid');
        let feedback = el.parentNode.querySelector('.validation-msg, .invalid-feedback');
        if (feedback) {
            feedback.textContent = '';
        }
    }
});