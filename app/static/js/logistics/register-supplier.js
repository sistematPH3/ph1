document.addEventListener("DOMContentLoaded", function() {
    const phoneInput = document.getElementById('phone');
    const phoneError = document.getElementById('phone-error');
    const emailInput = document.getElementById('email');
    const emailError = document.getElementById('email-error');
    const submitBtn = document.getElementById('submitBtn');

    const phoneRegex = /^\+?[0-9][0-9\-\s]{7,18}[0-9]$/;
    const emailRegex = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    function validateForm() {
        let isPhoneValid = phoneRegex.test(phoneInput.value);
        let isEmailValid = emailRegex.test(emailInput.value);
        
        submitBtn.disabled = (!isPhoneValid && phoneInput.value !== '') || (!isEmailValid && emailInput.value !== '');
    }

    phoneInput.addEventListener('input', function() {
        if (this.value.length === 0) {
            phoneError.textContent = '';
        } else if (!phoneRegex.test(this.value)) {
            phoneError.textContent = 'Formato inválido. Ej: +58 412-0000000';
            phoneError.className = 'validation-msg text-danger';
        } else {
            phoneError.textContent = 'Formato válido';
            phoneError.className = 'validation-msg text-success';
        }
        validateForm();
    });

    emailInput.addEventListener('input', function() {
        if (this.value.length === 0) {
            emailError.textContent = '';
        } else if (!emailRegex.test(this.value)) {
            emailError.textContent = 'Debe incluir "@" y un dominio válido';
            emailError.className = 'validation-msg text-danger';
        } else {
            emailError.textContent = 'Correo válido';
            emailError.className = 'validation-msg text-success';
        }
        validateForm();
    });

    validateForm();
});