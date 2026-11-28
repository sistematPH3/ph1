import time

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for

from .. import security_bp
from ..requests.auth_validators import REGLAS_PASSWORD, validar_email
from ..repositories.register_repository import RegisterRepository
from ..services.register_service import RegisterService

# Freno al registro masivo de cuentas automatizadas. Es un dict de modulo (en
# memoria del proceso, sin Flask-Limiter ni Redis).
_INTENTOS_REGISTRO = {}


def _limite_registro():
    """Tope de intentos y ventana efectiva, configurables por entorno.

    `REGISTRO_MAX_INTENTOS <= 0` significa DESACTIVADO: la ruta no cuenta
    intentos ni bloquea. Es el valor por defecto en desarrollo para no frenar
    las pruebas continuas; en produccion se define 5 en el entorno.
    """
    maximo = int(current_app.config.get('REGISTRO_MAX_INTENTOS', 0) or 0)
    ventana = int(current_app.config.get('REGISTRO_VENTANA_SEGUNDOS', 900) or 900)
    return maximo, ventana


def _excede_tope_registro(identificador):
    maximo, ventana = _limite_registro()
    if maximo <= 0:
        return False

    ahora = time.time()
    registro = _INTENTOS_REGISTRO.get(identificador)

    if not registro or ahora - registro['inicio'] > ventana:
        _INTENTOS_REGISTRO[identificador] = {'inicio': ahora, 'intentos': 1}
        return False

    registro['intentos'] += 1
    return registro['intentos'] > maximo


@security_bp.route('/check-email', methods=['POST'])
def check_email():
    """Comprueba si el correo ya existe. Devuelve siempre JSON."""
    data = request.get_json(silent=True) or {}
    email = data.get('email')

    if not validar_email(email):
        return jsonify({"exists": False, "error": "Por favor, ingrese un correo electrónico válido."}), 400

    existe = RegisterRepository.existe_usuario_por_email(email.strip())
    return jsonify({"exists": existe})


@security_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if _excede_tope_registro(request.remote_addr or 'desconocida'):
            flash("Demasiados intentos de registro. Por favor, intente más tarde.", "warning")
            return render_template('security/register.html', reglas_password=REGLAS_PASSWORD)

        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        resultado = RegisterService.registrar_usuario(name, email, password)

        if resultado["success"]:
            flash(resultado["message"], 'success')
            return redirect(url_for('security.login'))

        # Se muestra el mensaje real: antes la plantilla descartaba los avisos de
        # contrasena y de formato, y el usuario no veia ningun error.
        flash(resultado["message"], 'warning')

    return render_template('security/register.html', reglas_password=REGLAS_PASSWORD)
