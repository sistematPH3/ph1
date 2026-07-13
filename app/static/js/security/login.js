/**
 * Lógica de Validación e Interacción para el Inicio de Sesión
 * Archivo: app/static/js/security/login.js
 */

document.addEventListener('DOMContentLoaded', function() {
    // === ELEMENTOS DEL FORMULARIO ===
    const emailInput = document.querySelector('#email');
    const passwordInput = document.querySelector('#password');
    const togglePassword = document.querySelector('#togglePassword');

    // === 1. VALIDACIÓN VISUAL DEL CORREO ELECTRÓNICO ===
    if (emailInput) {
        emailInput.addEventListener('blur', function() {
            const errorDiv = document.getElementById('emailError');
            const container = this.closest('.input-with-icon');
            
            if (!errorDiv || !container) return;

            if (this.value.trim() !== "" && !this.value.includes('@')) {
                errorDiv.style.display = 'block';
                container.style.borderColor = '#ff4444';
            } else {
                errorDiv.style.display = 'none';
                container.style.borderColor = 'var(--ph-yellow)';
            }
        });
    }

    // === 2. MOSTRAR / OCULTAR CONTRASEÑA ===
    if (togglePassword && passwordInput) {
        togglePassword.addEventListener('click', function () {
            // 1. Detectar el estado actual
            const currentType = passwordInput.getAttribute('type');
            
            // 2. Cambiar al estado opuesto
            if (currentType === 'password') {
                passwordInput.setAttribute('type', 'text');
                // Al estar en texto (visible), mostramos el ojo abierto
                this.src = this.dataset.eyeOpen;
            } else {
                passwordInput.setAttribute('type', 'password');
                // Al estar en password (oculto), mostramos el ojo cerrado
                this.src = this.dataset.eyeClosed;
            }
        });
    }
});