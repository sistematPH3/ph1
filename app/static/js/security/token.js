document.addEventListener('DOMContentLoaded', function() {
    const forgotForm = document.getElementById('forgotForm');
    if (forgotForm) {
        const emailInput = document.getElementById('email');
        const errorMsg = document.getElementById('error-msg');
        const msj = document.getElementById('mensaje');

        emailInput.addEventListener('input', function() {
            const email = this.value;
            if (email.length > 0 && !email.includes('@')) {
                errorMsg.innerText = `Incluye un signo "@" en la dirección de correo electrónico.`;
                errorMsg.style.display = 'block';
            } else {
                errorMsg.style.display = 'none';
            }
        });

        forgotForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const email = emailInput.value.trim();
            msj.innerText = '';

            if (!email) {
                errorMsg.innerText = "Por favor ingrese su correo";
                errorMsg.style.display = 'block';
                return;
            }

            if (!email.includes('@')) {
                errorMsg.innerText = `Incluye un signo "@" en la dirección de correo electrónico. La dirección "${email}" no incluye el signo "@".`;
                errorMsg.style.display = 'block';
                return; 
            }

            errorMsg.style.display = 'none';
            msj.innerText = "Procesando...";
            msj.style.color = "#666";
            
            fetch(window.location.pathname, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email })
            })
            .then(res => res.json())
            .then(data => {
                msj.innerText = ""; 
                if (data.error) {
                    errorMsg.innerText = data.error;
                    errorMsg.style.display = 'block';
                } else {
                    msj.style.color = "green";
                    msj.innerText = data.message;
                }
            })
            .catch(err => {
                msj.innerText = "";
                errorMsg.innerText = "Error de conexión.";
                errorMsg.style.display = 'block';
            });
        });
    }

    const resetForm = document.getElementById('resetForm');
    if (resetForm) {
        const togglePassword = document.getElementById('togglePassword');
        const passwordInput = document.getElementById('new_password');
        const errorMsg = document.getElementById('error-msg');
        const msj = document.getElementById('mensaje');
        const container = document.getElementById('mensaje-container');

        if (togglePassword) {
            togglePassword.addEventListener('click', function () {
                const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
                passwordInput.setAttribute('type', type);

                if (type === 'text') {
                    this.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
                } else {
                    this.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22"></path></svg>';
                }
            });
        }

        passwordInput.addEventListener('input', function() {
            const pwd = this.value;
            
            if (pwd.length > 0 && (pwd.length < 6 || pwd.length > 12)) {
                errorMsg.innerText = `La contraseña debe tener entre 6 y 12 caracteres (actualmente tiene ${pwd.length}).`;
                errorMsg.style.display = 'block';
            } else {
                errorMsg.style.display = 'none';
            }
        });

        resetForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const pwd = passwordInput.value;
            
            errorMsg.style.display = 'none';
            msj.innerText = '';
            
            const oldLink = document.getElementById('btn-login');
            if(oldLink) oldLink.remove();

            if (!pwd) {
                errorMsg.innerText = "Por favor, ingresa tu nueva contraseña.";
                errorMsg.style.display = 'block';
                return;
            }

            if (pwd.length < 6 || pwd.length > 12) {
                errorMsg.innerText = `La contraseña debe tener entre 6 y 12 caracteres (actualmente tiene ${pwd.length}).`;
                errorMsg.style.display = 'block';
                return;
            }

            msj.innerText = "Guardando...";
            msj.style.color = "#666";
            
            fetch(window.location.pathname, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_password: pwd })
            })
            .then(res => res.json())
            .then(data => {
                msj.innerText = ""; 
                
                if(data.error) {
                    errorMsg.innerText = data.error;
                    errorMsg.style.display = 'block';
                } else {
                    msj.style.color = "green";
                    msj.innerText = data.message;
                    
                    resetForm.reset();
                    resetForm.style.display = 'none';
                    
                    const loginBtn = document.createElement('a');
                    loginBtn.href = "/auth/login"; 
                    loginBtn.innerText = "Ir a Iniciar Sesión";
                    loginBtn.className = "login-link";
                    loginBtn.id = "btn-login";
                    loginBtn.style.display = "block"; 
                    container.appendChild(loginBtn);
                }
            })
            .catch(err => {
                msj.innerText = "";
                errorMsg.innerText = "Error de conexión.";
                errorMsg.style.display = 'block';
            });
        });
    }
});