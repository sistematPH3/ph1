from app.extensions import db
from sqlalchemy import text

class UserListRepository:
    @staticmethod
    def get_active_users():
        query = text("""
            SELECT u.id, u.name, u.email, u.role_id, ul.location_id 
            FROM users u
            LEFT JOIN user_locations ul ON u.id = ul.user_id
            WHERE u.is_active = true
        """)
        return db.session.execute(query).fetchall()

    @staticmethod
    def update_user_location(user_id, location_id):
        try:
            delete_query = text("DELETE FROM user_locations WHERE user_id = :user_id")
            db.session.execute(delete_query, {"user_id": user_id})
            
            if location_id is not None:
                insert_query = text("INSERT INTO user_locations (user_id, location_id) VALUES (:user_id, :location_id)")
                db.session.execute(insert_query, {"user_id": user_id, "location_id": location_id})
                
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False