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

    function mostrarError(errorMsg, texto, tipo) {
        errorMsg.innerText = texto;
        errorMsg.style.display = 'block';
        if (tipo) {
            errorMsg.dataset.tipo = tipo;
        } else {
            delete errorMsg.dataset.tipo;
        }
    }

    function ocultarError(errorMsg) {
        errorMsg.innerText = '';
        errorMsg.style.display = 'none';
        delete errorMsg.dataset.tipo;
    }

    const forgotForm = document.getElementById('forgotForm');
    if (forgotForm) {
        const emailInput = document.getElementById('email');
        const errorMsg = document.getElementById('error-msg');
        const msj = document.getElementById('mensaje');
        const checkUrl = forgotForm.dataset.checkUrl
            || (window.location.pathname.replace(/\/$/, '') + '/check-email');

        let temporizador = null;
        let controlador = null;

        function cancelarConsulta() {
            if (temporizador) {
                clearTimeout(temporizador);
                temporizador = null;
            }
            if (controlador) {
                controlador.abort();
                controlador = null;
            }
        }

        async function consultarExistencia(email) {
            if (controlador) controlador.abort();
            const controladorActual = new AbortController();
            controlador = controladorActual;

            let respuesta;
            try {
                respuesta = await fetch(checkUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email }),
                    signal: controladorActual.signal
                });
            } catch (e) {
                // Si la consulta falla no se bloquea al usuario: el submit
                // vuelve a validar contra el servidor.
                return;
            } finally {
                if (controlador === controladorActual) controlador = null;
            }

            // 429 u otro error de la consulta: se ignora. La validacion
            // definitiva sigue siendo el submit.
            if (!respuesta.ok) return;

            let data;
            try {
                data = await respuesta.json();
            } catch (e) {
                return;
            }

            // Si el correo cambio mientras llegaba la respuesta, se descarta.
            if (emailInput.value.trim() !== email) return;

            if (data.existe === false) {
                mostrarError(errorMsg,
                    'El correo ingresado no existe en el sistema.', 'existencia');
            } else if (data.activa === false) {
                mostrarError(errorMsg,
                    'Tu cuenta aún no está activa. Contacta al administrador.', 'inactiva');
            } else if (errorMsg.dataset.tipo === 'existencia'
                    || errorMsg.dataset.tipo === 'inactiva') {
                ocultarError(errorMsg);
            }
        }

        function programarConsulta(email) {
            if (temporizador) clearTimeout(temporizador);
            temporizador = setTimeout(function () {
                temporizador = null;
                consultarExistencia(email);
            }, 500);
        }

        emailInput.addEventListener('input', function () {
            const email = this.value.trim();
            cancelarConsulta();
            ocultarError(errorMsg);

            if (email.length > 0 && !window.EmailRules.esValido(email, emailInput)) {
                mostrarError(errorMsg, window.EmailRules.mensaje(), 'formato');
                return;
            }
            if (!email) return;

            // Formato valido: se consulta la existencia al dejar de escribir.
            programarConsulta(email);
        });

        emailInput.addEventListener('blur', function () {
            const email = this.value.trim();
            cancelarConsulta();
            if (!email || !window.EmailRules.esValido(email, emailInput)) return;
            consultarExistencia(email);
        });

        forgotForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            cancelarConsulta();
            const email = emailInput.value.trim();
            msj.innerText = '';

            if (!email) {
                mostrarError(errorMsg, 'Por favor ingrese su correo.', 'formato');
                return;
            }
            if (!window.EmailRules.esValido(email, emailInput)) {
                mostrarError(errorMsg, window.EmailRules.mensaje(), 'formato');
                return;
            }

            ocultarError(errorMsg);
            msj.innerText = 'Procesando...';
            msj.style.color = '#666';

            const data = await enviarJSON(window.location.pathname, { email: email });
            msj.innerText = '';

            if (data.error) {
                mostrarError(errorMsg, data.error, 'servidor');
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
