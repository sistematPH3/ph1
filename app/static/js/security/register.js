document.addEventListener('DOMContentLoaded', function() {
    // 1. Referencias de elementos
    const form = document.querySelector('form');
    const nameInput = document.getElementById('name-input');
    const emailInput = document.getElementById('email-input');
    const passwordInput = document.getElementById('password-input');
    const togglePassword = document.getElementById('toggle-password');
    
    const nameError = document.getElementById('name-error');
    const emailError = document.getElementById('email-error');
    
    // El error de password lo buscamos o lo creamos si no existe
    let passError = document.querySelector('.password-wrapper + .error-hint-diego');
    if (!passError) {
        passError = document.createElement('div');
        passError.className = 'error-hint-diego';
        passwordInput.closest('.form-group').appendChild(passError);
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const urlCheck = emailInput.getAttribute('data-url');
    const urlOpen = togglePassword.getAttribute('data-eye-open');
    const urlClosed = togglePassword.getAttribute('data-eye-closed');

    // --- FUNCIONES DE APOYO ---
    function mostrarError(input, divError, mensaje) {
        divError.textContent = mensaje;
        divError.style.display = 'block';
        input.classList.add('input-error-border');
    }

    function ocultarError(input, divError) {
        divError.style.display = 'none';
        input.classList.remove('input-error-border');
    }

// Nombre: Límite de 40 caracteres
nameInput.addEventListener('input', function() {
    const nombre = nameInput.value;
    
    if (nombre.length === 0) {
        ocultarError(nameInput, nameError);
    } else if (nombre.length === 40) {
        // Se activa justo cuando llega al límite del maxlength físico
        mostrarError(nameInput, nameError, "Has alcanzado el límite de 40 caracteres.");
    } else {
        ocultarError(nameInput, nameError);
    }
});

    // Correo: Validación de formato y existencia (Blur)
    emailInput.addEventListener('blur', async function() {
        const valor = emailInput.value.trim();
        if (valor === "") return;

        if (!emailRegex.test(valor)) {
            mostrarError(emailInput, emailError, "El formato del correo no es válido.");
            return;
        }

        try {
            const response = await fetch(urlCheck, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: valor })
            });
            const data = await response.json();
            if (data.exists) {
                mostrarError(emailInput, emailError, "Este correo ya está registrado.");
            }
        } catch (e) { console.error("Error validando email:", e); }
    });

    emailInput.addEventListener('input', () => ocultarError(emailInput, emailError));

    // Contraseña: Límite de 12 y longitud mínima
    passwordInput.addEventListener('input', function() {
        const pass = passwordInput.value;
        if (pass.length === 0) {
            ocultarError(passwordInput, passError);
        } else if (pass.length < 6) {
            mostrarError(passwordInput, passError, "La contraseña debe tener mínimo 6 caracteres.");
        } else if (pass.length === 12) {
            mostrarError(passwordInput, passError, "Has alcanzado el límite de 12 caracteres.");
        } else {
            ocultarError(passwordInput, passError);
        }
    });

    // --- FUNCIÓN DEL OJITO ---
    togglePassword.addEventListener('click', function() {
        const tipo = passwordInput.type === 'password' ? 'text' : 'password';
        passwordInput.type = tipo;
        togglePassword.src = (tipo === 'text') ? urlOpen : urlClosed;
    });

    // --- VALIDACIÓN FINAL AL ENVIAR (CAMPOS VACÍOS) ---
    form.addEventListener('submit', function(e) {
        let esValido = true;

        if (nameInput.value.trim() === "") {
            mostrarError(nameInput, nameError, "Por favor, ingresa tu nombre.");
            esValido = false;
        }
        if (emailInput.value.trim() === "") {
            mostrarError(emailInput, emailError, "El correo es obligatorio.");
            esValido = false;
        }
        if (passwordInput.value.trim() === "") {
            mostrarError(passwordInput, passError, "Debes crear una contraseña.");
            esValido = false;
        }

        if (!esValido) e.preventDefault();
    });
});