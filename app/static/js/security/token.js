document.addEventListener('DOMContentLoaded', function () {
    /**
     * Antes se hacia res.json() a ciegas: si el servidor devolvia HTML (415, 400
     * o un 500 de Flask) la conversion lanzaba y el catch mostraba siempre
     * "Error de conexion", ocultando la causa real.
     */
    async function enviarJSON(url, payload) {
        let respuesta;
        try {
            respuesta = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } catch (e) {
            return { error: 'No se pudo conectar con el servidor. Verifique su red.' };
        }

        let cuerpo = null;
        const tipo = respuesta.headers.get('content-type') || '';
        if (tipo.includes('application/json')) {
            try { cuerpo = await respuesta.json(); } catch (e) { cuerpo = null; }
        }

        if (cuerpo && (cuerpo.error || cuerpo.message)) return cuerpo;

        if (respuesta.status === 429) {
            return { error: 'Demasiados intentos. Por favor, espere unos minutos.' };
        }
        if (respuesta.status === 415 || respuesta.status === 400) {
            return { error: 'La solicitud no fue válida. Recargue la página e intente de nuevo.' };
        }
        if (!respuesta.ok) {
            return { error: `Ocurrió un problema en el servidor (${respuesta.status}). Intente nuevamente.` };
        }
        return { error: 'Respuesta inesperada del servidor.' };
    }

    function mostrarError(errorMsg, texto) {
        errorMsg.innerText = texto;
        errorMsg.style.display = 'block';
    }

    const forgotForm = document.getElementById('forgotForm');
    if (forgotForm) {
        const emailInput = document.getElementById('email');
        const errorMsg = document.getElementById('error-msg');
        const msj = document.getElementById('mensaje');

        emailInput.addEventListener('input', function () {
            const email = this.value;
            if (email.length > 0 && !window.EmailRules.esValido(email, emailInput)) {
                mostrarError(errorMsg, window.EmailRules.mensaje());
            } else {
                errorMsg.style.display = 'none';
            }
        });

        forgotForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            const email = emailInput.value.trim();
            msj.innerText = '';

            if (!email) {
                mostrarError(errorMsg, 'Por favor ingrese su correo.');
                return;
            }
            if (!window.EmailRules.esValido(email, emailInput)) {
                mostrarError(errorMsg, window.EmailRules.mensaje());
                return;
            }

            errorMsg.style.display = 'none';
            msj.innerText = 'Procesando...';
            msj.style.color = '#666';

            const data = await enviarJSON(window.location.pathname, { email: email });
            msj.innerText = '';

            if (data.error) {
                mostrarError(errorMsg, data.error);
            } else {
                msj.style.color = 'green';
                msj.innerText = data.message;
            }
        });
    }

    const resetForm = document.getElementById('resetForm');
    if (resetForm) {
        const togglePassword = document.getElementById('togglePassword');
        const passwordInput = document.getElementById('new_password');
        const errorMsg = document.getElementById('error-msg');
        const msj = document.getElementById('mensaje');
        const container = document.getElementById('mensaje-container');

        // Componente compartido con el registro: las 3 reglas se muestran desde
        // el inicio y se van marcando en verde. El error rojo solo al enviar.
        const validador = window.PasswordRules.init({
            input: passwordInput,
            lista: document.getElementById('password-rules'),
            contador: document.getElementById('password-counter')
        });

        if (togglePassword) {
            togglePassword.addEventListener('click', function () {
                const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
                passwordInput.setAttribute('type', type);
                togglePassword.setAttribute('aria-label', type === 'text' ? 'Ocultar contraseña' : 'Ver contraseña');

                if (type === 'text') {
                    this.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
                } else {
                    this.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22"></path></svg>';
                }
            });
        }

        passwordInput.addEventListener('input', function () {
            // Mientras se escribe solo se actualizan las marcas verdes; el error
            // en rojo se reserva para el envio, para no saltar a cada tecla.
            if (!this.value) errorMsg.style.display = 'none';
        });

        resetForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            const pwd = passwordInput.value;

            errorMsg.style.display = 'none';
            msj.innerText = '';

            const botonPrevio = document.getElementById('btn-login');
            if (botonPrevio) botonPrevio.remove();

            if (!pwd) {
                mostrarError(errorMsg, 'Por favor, ingresa tu nueva contraseña.');
                return;
            }

            const problema = validador ? validador.problema() : '';
            if (problema) {
                mostrarError(errorMsg, problema);
                return;
            }

            msj.innerText = 'Guardando...';
            msj.style.color = '#666';

            const data = await enviarJSON(window.location.pathname, { new_password: pwd });
            msj.innerText = '';

            if (data.error) {
                mostrarError(errorMsg, data.error);
            } else {
                msj.style.color = 'green';
                msj.innerText = data.message;

                resetForm.reset();
                resetForm.style.display = 'none';

                const loginBtn = document.createElement('a');
                loginBtn.href = '/auth/login';
                loginBtn.innerText = 'Ir a Iniciar Sesión';
                loginBtn.className = 'login-link';
                loginBtn.id = 'btn-login';
                loginBtn.style.display = 'block';
                container.appendChild(loginBtn);
            }
        });
    }
});
