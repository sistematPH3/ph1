import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))


load_dotenv(os.path.join(basedir, '../.env')) 


print(f"DEBUG: DATABASE_URL cargado: {os.environ.get('DATABASE_URL')}")

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una-clave-secreta-por-defecto'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuración de Mail
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')