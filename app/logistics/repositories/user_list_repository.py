from app.models import User

class UserRepository:
    @staticmethod
    def get_active_users():
      
        return User.query.filter_by(is_active=True).all()