import smtplib
from email.message import EmailMessage
import secrets
from datetime import datetime, timedelta

# Importamos las funciones del repositorio, incluyendo la nueva consultar_vigencia_token
from app.security.repositories.token_repositories import guardar_token, actualizar_password_con_token, consultar_vigencia_token

def enviar_correo_recuperacion(email_destino, token):
    email_emisor = "sistemat3.ph@gmail.com"
    password_emisor = "xephkblwzhjownnz" 

    msg = EmailMessage()
    msg['Subject'] = 'Recuperación de Contraseña - Sistema Pizza Hut'
    msg['From'] = email_emisor
    msg['To'] = email_destino

    enlace = f"http://127.0.0.1:5000/auth/reset-password/{token}"

    msg.set_content(f"""\
    Hola,

    Has solicitado recuperar tu contraseña en el sistema de Pizza Hut.
    Haz clic en el siguiente enlace para crear una nueva:
    
    {enlace}
    
    Este enlace expirará en 1 hora.
    Si no solicitaste este cambio, puedes ignorar este correo.
    """)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(email_emisor, password_emisor)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Error al enviar el correo: {e}")

def solicitar_recuperacion(email):
    """
    Genera el token, calcula la expiración, lo guarda en la nueva tabla 
    y dispara el correo.
    """
    token_seguro = secrets.token_urlsafe(32)
    expiracion = datetime.now() + timedelta(hours=1) 
    
    if not guardar_token(email, token_seguro, expiracion):
        return False
        
    enviar_correo_recuperacion(email, token_seguro)
    return True

def cambiar_password(token, nueva_password):
    """
    Pasa la solicitud al repositorio para que valide el token 
    y ejecute el cambio.
    """
    return actualizar_password_con_token(token, nueva_password)

def verificar_vigencia_token(token):
    """
    Se comunica con el repositorio para saber si el token existe y aún está vigente en tiempo.
    """
    return consultar_vigencia_token(token)