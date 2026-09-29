import time

from flask import current_app, jsonify, render_template, request

from app.security import security_bp
from app.extensions import db
from app.models import LoginAudit, User
from app.security.services.token_services import (
    cambiar_password,
    solicitar_recuperacion,
    verificar_vigencia_token,
)
from app.security.requests.auth_validators import REGLAS_PASSWORD
from app.security.requests.token_validators import (
    validar_nueva_password,
    validar_solicitud_recuperacion,
)


# --- Limitador de intentos -------------------------------------------------
# Sin dependencias extra (no hay Flask-Limiter ni Redis en el proyecto).
# Es por proceso: se reinicia al reiniciar la app y no se comparte entre
# workers. Para varias instancias, mover a Redis.
_INTENTOS = {}


def _clave_limite(prefijo, identificador):
    return f"{prefijo}:{identificador}"


def _excede_tope(prefijo, identificador):
    cfg = current_app.config
    maximo = cfg.get('RECUPERACION_MAX_INTENTOS', 5)
    ventana = cfg.get('RECUPERACION_VENTANA_SEGUNDOS', 900)

    ahora = time.time()
    clave = _clave_limite(prefijo, identificador)
    registro = _INTENTOS.get(clave)

    if not registro or ahora - registro['inicio'] > ventana:
        _INTENTOS[clave] = {'inicio': ahora, 'intentos': 1}
        return False

    registro['intentos'] += 1
    return registro['intentos'] > maximo


def _reiniciar_limite(prefijo, identificador):
    _INTENTOS.pop(_clave_limite(prefijo, identificador), None)


def _datos_json():
    """Nunca revienta con 415/400: el JS siempre espera JSON."""
    return request.get_json(silent=True) or {}


@security_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('security/token_forgot.html')

    # Se limita por IP para frenar envio masivo de correos.
    if _excede_tope('forgot', request.remote_addr or 'desconocida'):
        return jsonify({
            "error": "Demasiados intentos. Por favor, espere unos minutos antes de volver a intentar."
        }), 429

    es_valido, mensaje_error = validar_solicitud_recuperacion(_datos_json())
    if not es_valido:
        return jsonify({"error": mensaje_error}), 400

    estado = solicitar_recuperacion(_datos_json().get('email'))

    if estado == "error_envio":
        return jsonify({
            "error": "Ocurrió un problema al enviar el correo. Intente nuevamente o contacte al administrador."
        }), 500

    # Mismo mensaje exista o no la cuenta: no se puede enumerar usuarios.
    return jsonify({
        "message": "Correo comprobado, recibirás un enlace al correo con las siguientes instrucciones que debes seguir."
    }), 200


@security_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if request.method == 'GET':
        es_valido = verificar_vigencia_token(token)
        return render_template(
            'security/token_reset.html',
            token=token,
            token_valido=es_valido,
            reglas_password=REGLAS_PASSWORD,
        )

    # Se limita por token para frenar intentos de adivinar o reutilizar enlaces.
    if _excede_tope('reset', token):
        return jsonify({
            "error": "Demasiados intentos con este enlace. Solicita uno nuevo."
        }), 429

    es_valido, mensaje_error = validar_nueva_password(_datos_json())
    if not es_valido:
        return jsonify({"error": mensaje_error}), 400

    # El servicio devuelve el user_id: la ruta ya no busca el token por su
    # cuenta, que era la causa del UnboundLocalError y del 500 tras cambiar la
    # contraseña.
    exito, user_id = cambiar_password(token, _datos_json().get('new_password'))

    if not exito:
        return jsonify({"error": "El enlace de recuperación es inválido o ha expirado."}), 400

    # La auditoria va en su propia transaccion: si falla, la contraseña ya esta
    # cambiada y el token consumido, asi que no se responde 500 al usuario.
    try:
        _registrar_auditoria(user_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Recuperacion: la contraseña se cambio pero fallo el registro de auditoria"
        )

    return jsonify({
        "message": "Tu contraseña ha sido actualizada con éxito. Ya puedes iniciar sesión."
    }), 200


def _registrar_auditoria(user_id):
    """Registra CAMBIO_CONTRASENA. Si el usuario no existe, no rompe el flujo."""
    if not user_id:
        return False

    usuario = db.session.get(User, user_id)
    if usuario is None:
        current_app.logger.warning(
            f"Recuperacion: no se encontro el usuario {user_id} para auditar"
        )
        return False

    sede_id = usuario.locations[0].id if usuario.locations else None

    db.session.add(LoginAudit(
        user_id=usuario.id,
        location_id=sede_id,
        role_id=usuario.role_id,
        action='CAMBIO_CONTRASENA',
    ))
    db.session.commit()
    return True
