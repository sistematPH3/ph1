from app.extensions import db
from sqlalchemy import text

class UserListRepository:
    @staticmethod
    def get_active_users():
        query = text("""
            SELECT u.id, u.name, u.email, u.role_id, array_remove(array_agg(ul.location_id), NULL) as location_ids
            FROM users u
            LEFT JOIN user_locations ul ON u.id = ul.user_id
            WHERE u.is_active = true 
            AND u.role_id IN (2, 3, 4, 6)
            GROUP BY u.id, u.name, u.email, u.role_id
        """)
        return db.session.execute(query).fetchall()

    @staticmethod
    def update_user_locations(user_id, location_ids):
        try:
            delete_query = text("DELETE FROM user_locations WHERE user_id = :user_id")
            db.session.execute(delete_query, {"user_id": user_id})
            
            if location_ids:
                insert_query = text("INSERT INTO user_locations (user_id, location_id) VALUES (:user_id, :location_id)")
                for loc_id in location_ids:
                    db.session.execute(insert_query, {"user_id": user_id, "location_id": loc_id})
                
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False