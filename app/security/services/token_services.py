import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from flask import current_app, url_for

from app.security.repositories.token_repositories import (
    ahora,
    actualizar_password_con_token,
    consultar_vigencia_token,
    eliminar_token,
    guardar_token,
    obtener_usuario_por_email,
)
from app.security.repositories.token_repositories import (
    purgar_tokens_vencidos as _purgar_tokens_vencidos,
)

VIGENCIA_POR_DEFECTO_HORAS = 1


def construir_enlace_recuperacion(token):
    """
    Genera el enlace publico del reset.

    Se usa url_for(..., _external=True) en vez de una URL fija: si PUBLIC_BASE_URL
    esta configurado se respeta ese host (produccion detras de proxy) y, si no,
    se deriva de la peticion actual. El correo nunca apunta a 127.0.0.1.
    """
    base = (current_app.config.get('PUBLIC_BASE_URL') or '').rstrip('/')
    ruta = url_for('security.reset_password', token=token)
    return f"{base}{ruta}" if base else url_for(
        'security.reset_password', token=token, _external=True
    )


def enviar_correo_recuperacion(email_destino, token):
    """
    Envia el correo con el enlace de recuperacion.

    Todo el cuerpo esta protegido: si falla la construccion del mensaje o el
    envio, se registra la causa real y se devuelve False. Antes solo se cubria
    el bloque SMTP y un error posterior se escapaba como 500 sin detalle.
    """
    cfg = current_app.config
    emisor = cfg.get('MAIL_USERNAME')
    password = cfg.get('MAIL_PASSWORD')
    servidor = cfg.get('MAIL_SERVER') or 'smtp.gmail.com'
    puerto = cfg.get('MAIL_PORT') or 465
    timeout = cfg.get('MAIL_TIMEOUT') or 15

    if not emisor or not password:
        current_app.logger.error(
            "Recuperacion: faltan MAIL_USERNAME o MAIL_PASSWORD en la configuracion. "
            "Revisa el archivo .env; no hay valores por defecto."
        )
        return False

    try:
        enlace = construir_enlace_recuperacion(token)
        horas = cfg.get('RECUPERACION_VIGENCIA_HORAS', VIGENCIA_POR_DEFECTO_HORAS)

        msg = EmailMessage()
        msg['Subject'] = 'Recuperación de Contraseña - Sistema Pizza Hut'
        msg['From'] = emisor
        msg['To'] = email_destino
        msg.set_content(
            "Hola,\n\n"
            "Has solicitado recuperar tu contraseña en el sistema de Pizza Hut.\n"
            "Haz clic en el siguiente enlace para crear una nueva:\n\n"
            f"{enlace}\n\n"
            f"Este enlace expira en {horas} hora(s) y solo puede usarse una vez.\n"
            "Si no solicitaste este cambio, puedes ignorar este correo.\n"
        )

        if cfg.get('MAIL_USE_SSL', True):
            with smtplib.SMTP_SSL(servidor, puerto, timeout=timeout) as smtp:
                smtp.login(emisor, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(servidor, puerto, timeout=timeout) as smtp:
                smtp.ehlo()
                if cfg.get('MAIL_USE_TLS'):
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(emisor, password)
                smtp.send_message(msg)

        return True
    except Exception:
        current_app.logger.exception(
            f"Recuperacion: fallo el envio del correo a {email_destino}"
        )
        return False


def solicitar_recuperacion(email):
    """
    Genera el token, lo guarda y envia el correo.

    Devuelve "ok" exista o no el correo: la respuesta al cliente es siempre
    identica para no permitir enumerar cuentas. El envio solo se intenta si el
    usuario existe y esta activo.
    """
    token_seguro = secrets.token_urlsafe(32)
    horas = current_app.config.get('RECUPERACION_VIGENCIA_HORAS', VIGENCIA_POR_DEFECTO_HORAS)
    expiracion = ahora() + timedelta(hours=horas)

    guardado, _user_id = guardar_token(email, token_seguro, expiracion)
    if not guardado:
        current_app.logger.info(
            "Recuperacion: solicitud para un correo no registrado o inactivo. "
            "Se responde igual para no revelar que cuentas existen."
        )
        return "ok"

    if not enviar_correo_recuperacion(email, token_seguro):
        # Sin correo entregado el token no sirve: se elimina para no dejar
        # vigentes tokens que el usuario nunca recibio.
        eliminar_token(token_seguro)
        return "error_envio"

    return "ok"


def cambiar_password(token, nueva_password):
    """
    Cambia la contraseña consumiendo el token.

    Devuelve (ok, user_id) para que la ruta audite sin volver a consultar el
    token por su cuenta: antes lo hacia y podia desincronizarse del servicio.
    """
    return actualizar_password_con_token(token, nueva_password)


def verificar_vigencia_token(token):
    return consultar_vigencia_token(token)


def usuario_existe_y_activo(email):
    return obtener_usuario_por_email(email) is not None


def purgar_tokens_vencidos():
    """
    Limpia tokens vencidos o ya usados.

    No se llama en cada peticion: conectala a una tarea programada o a un
    comando de mantenimiento para que la tabla no crezca sin control.
    """
    return _purgar_tokens_vencidos()
