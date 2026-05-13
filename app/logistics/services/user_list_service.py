from app.logistics.repositories.user_list_repository import UserRepository

class UserService:
    @staticmethod
    def get_users_list():
        users = UserRepository.get_active_users()
        
        users_data = []
        for user in users:
            users_data.append({
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role_id": user.role_id
            })
            
        return users_data