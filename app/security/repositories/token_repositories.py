from datetime import datetime

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.security_model import User, PasswordRecovery


def ahora():
    """
    Unica fuente de tiempo del modulo.

    La columna expires_at es naive, asi que todas las escrituras y comparaciones
    deben usar la misma base. Antes se mezclaban datetime.now() con el default
    datetime.utcnow() del modelo, lo que dejaba tokens con vigencia incoherente.
    """
    return datetime.now()


def obtener_usuario_por_email(email):
    """Devuelve un usuario activo o None. No filtra por rol (0 = invitado)."""
    if not email:
        return None
    return User.query.filter(
        User.email == email.strip(),
        User.is_active.is_(True),
    ).first()


def invalidar_tokens_previos(user_id, excepto_token=None):
    """
    Marca como usados todos los tokens pendientes del usuario.

    Sin esto un correo antiguo sigue cambiando la contraseña despues de que el
    usuario haya generado uno nuevo.
    """
    try:
        consulta = PasswordRecovery.query.filter(
            PasswordRecovery.user_id == user_id,
            PasswordRecovery.used.is_(False),
        )
        if excepto_token:
            consulta = consulta.filter(PasswordRecovery.token != excepto_token)

        tokens = consulta.all()
        for token in tokens:
            token.used = True

        db.session.commit()
        return len(tokens)
    except Exception:
        db.session.rollback()
        raise


def guardar_token(email, token, expiracion):
    """
    Crea el token de recuperacion e invalida los anteriores del mismo usuario.

    Devuelve (ok, user_id). No crea nada si el correo no pertenece a un
    usuario activo.
    """
    try:
        usuario = obtener_usuario_por_email(email)
        if not usuario:
            return False, None

        invalidar_tokens_previos(usuario.id)

        recuperacion = PasswordRecovery(
            user_id=usuario.id,
            token=token,
            created_at=ahora(),
            expires_at=expiracion,
            used=False,
        )
        db.session.add(recuperacion)
        db.session.commit()
        return True, usuario.id
    except Exception as e:
        db.session.rollback()
        print(f"Error en BD al guardar token: {e}")
        return False, None


def eliminar_token(token):
    """Borra un token. Se usa si el envio del correo falla, para no dejar huerfanos."""
    try:
        PasswordRecovery.query.filter(PasswordRecovery.token == token).delete(
            synchronize_session=False
        )
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


def actualizar_password_con_token(token, nueva_password):
    """
    Valida el token, cambia la contraseña y lo consume en una sola transaccion.

    Devuelve (ok, user_id). El token queda con used=True en lugar de borrarse:
    asi no se puede reusar y queda rastro para auditoria.
    """
    try:
        recuperacion = PasswordRecovery.query.filter(
            PasswordRecovery.token == token,
            PasswordRecovery.used.is_(False),
            PasswordRecovery.expires_at > ahora(),
        ).first()

        if not recuperacion:
            return False, None

        usuario = User.query.get(recuperacion.user_id)
        if not usuario:
            return False, None

        usuario.password_hash = generate_password_hash(nueva_password)
        recuperacion.used = True
        db.session.commit()
        return True, usuario.id
    except Exception as e:
        db.session.rollback()
        print(f"Error al procesar el cambio de contraseña: {e}")
        return False, None


def consultar_vigencia_token(token):
    """True si el token existe, no fue usado y sigue dentro de su vigencia."""
    try:
        return PasswordRecovery.query.filter(
            PasswordRecovery.token == token,
            PasswordRecovery.used.is_(False),
            PasswordRecovery.expires_at > ahora(),
        ).first() is not None
    except Exception:
        db.session.rollback()
        print("Error al consultar la vigencia del token")
        return False


def purgar_tokens_vencidos():
    """
    Elimina tokens vencidos o ya usados.

    No se invoca en cada peticion: uselo desde una tarea programada o al
    iniciar la app, para que la tabla no crezca sin control.
    """
    try:
        vencidos = PasswordRecovery.query.filter(
            db.or_(
                PasswordRecovery.expires_at <= ahora(),
                PasswordRecovery.used.is_(True),
            )
        ).delete(synchronize_session=False)
        db.session.commit()
        return vencidos
    except Exception:
        db.session.rollback()
        return 0
