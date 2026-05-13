from app.models.security_model import User 

class LoginRepository:
    @staticmethod
    def obtener_usuario_por_email(email):
        # Buscamos en la tabla 'users' por la columna 'email'
        return User.query.filter_by(email=email).first()