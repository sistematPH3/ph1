document.addEventListener('DOMContentLoaded', function() {
    // 1. Referencias de elementos
    const form = document.querySelector('form');
    const nameInput = document.getElementById('name-input');
    const emailInput = document.getElementById('email-input');
    const passwordInput = document.getElementById('password-input');
    const togglePassword = document.getElementById('toggle-password');

    const nameError = document.getElementById('name-error');
    const emailError = document.getElementById('email-error');
    const passError = document.getElementById('password-error-slot');

    const urlCheck = emailInput.getAttribute('data-url');
    const urlOpen = togglePassword.getAttribute('data-eye-open');
    const urlClosed = togglePassword.getAttribute('data-eye-closed');

    // El formato del correo lo decide el backend: se reutiliza su patron para
    // que el JS no acepte algo que el servidor vaya a rechazar.
    const correo = window.EmailRules;

    // --- FUNCIONES DE APOYO ---
    function mostrarError(input, divError, mensaje) {
        if (!divError) return;
        divError.textContent = mensaje;
        divError.style.display = 'block';
        divError.classList.add('error-visible');
        if (input) input.classList.add('input-error-border');
    }

    function ocultarError(input, divError) {
        if (!divError) return;
        divError.textContent = '';
        divError.style.display = 'none';
        divError.classList.remove('error-visible');
        if (input) input.classList.remove('input-error-border');
    }

    // --- Contraseña: checklist vivo (reglas desde el backend) ---
    // Antes era un else-if que mostraba un solo error y ademas marcaba
    // "limite alcanzado" como fallo justo en 12 caracteres, que es valido.
    const validador = window.PasswordRules.init({
        input: passwordInput,
        lista: document.getElementById('password-rules'),
        contador: document.getElementById('password-counter')
    });

    // --- Correo: formato y existencia (Blur) ---
    emailInput.addEventListener('blur', async function() {
        const valor = emailInput.value.trim();
        if (valor === "") return;

        if (!correo.esValido(valor, emailInput)) {
            mostrarError(emailInput, emailError, correo.mensaje());
            return;
        }

        try {
            const response = await fetch(urlCheck, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: valor })
            });

            const tipo = response.headers.get('content-type') || '';
            const data = tipo.includes('application/json') ? await response.json() : null;
            if (!data) return;

            if (data.exists) {
                mostrarError(emailInput, emailError, "Este correo ya está registrado.");
            } else if (data.error) {
                mostrarError(emailInput, emailError, data.error);
            }
        } catch (e) {
            // Si la comprobacion falla se deja pasar: el backend volvera a validar.
            console.warn("No se pudo comprobar el correo:", e);
        }
    });

    emailInput.addEventListener('input', () => ocultarError(emailInput, emailError));

    // --- FUNCION DEL OJITO ---
    togglePassword.addEventListener('click', function() {
        const tipo = passwordInput.type === 'password' ? 'text' : 'password';
        passwordInput.type = tipo;
        togglePassword.src = (tipo === 'text') ? urlOpen : urlClosed;
    });

    // --- VALIDACION FINAL AL ENVIAR ---
    form.addEventListener('submit', function(e) {
        let esValido = true;

        if (nameInput.value.trim() === "") {
            mostrarError(nameInput, nameError, "Por favor, ingresa tu nombre.");
            esValido = false;
        }
        if (emailInput.value.trim() === "") {
            mostrarError(emailInput, emailError, "El correo es obligatorio.");
            esValido = false;
        } else if (!correo.esValido(emailInput.value, emailInput)) {
            // Sin esto, un correo mal formado se colaba si nunca hubo blur.
            mostrarError(emailInput, emailError, correo.mensaje());
            esValido = false;
        }
        if (passwordInput.value.trim() === "") {
            mostrarError(passwordInput, passError, "Debes crear una contraseña.");
            esValido = false;
        } else if (validador) {
            const problema = validador.problema();
            if (problema) {
                mostrarError(passwordInput, passError, problema);
                esValido = false;
            }
        }

        if (!esValido) e.preventDefault();
    });
});
