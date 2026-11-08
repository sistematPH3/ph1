from app.logistics.repositories.user_list_repository import UserListRepository

class UserListService:
    @staticmethod
    def get_users_list():
        users = UserListRepository.get_active_users()
        users_data = []
        for row in users:
            users_data.append({
                "id": row.id,
                "name": row.name,
                "email": row.email,
                "role_id": row.role_id,
                "location_ids": row.location_ids or []
            })
        return users_data

    @staticmethod
    def assign_locations(user_id, location_ids):
        return UserListRepository.update_user_locations(user_id, location_ids)