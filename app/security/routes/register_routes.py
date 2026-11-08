from flask import flash, jsonify, redirect, render_template, request, url_for

from .. import security_bp
from ..requests.auth_validators import REGLAS_PASSWORD, validar_email
from ..repositories.register_repository import RegisterRepository
from ..services.register_service import RegisterService

# Freno al registro masivo de cuentas automatizadas.
_INTENTOS_REGISTRO = {}
MAX_INTENTOS_REGISTRO = 5
VENTANA_REGISTRO_SEGUNDOS = 900


def _excede_tope_registro(identificador):
    import time
    ahora = time.time()
    registro = _INTENTOS_REGISTRO.get(identificador)

    if not registro or ahora - registro['inicio'] > VENTANA_REGISTRO_SEGUNDOS:
        _INTENTOS_REGISTRO[identificador] = {'inicio': ahora, 'intentos': 1}
        return False

    registro['intentos'] += 1
    return registro['intentos'] > MAX_INTENTOS_REGISTRO


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
