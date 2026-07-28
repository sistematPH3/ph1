from app import create_app
from app.extensions import db
from app.models.security_model import User, Role
from app.models import Location
from werkzeug.security import generate_password_hash
from sqlalchemy import text

app = create_app()

def seed_database():
    with app.app_context():
        print("--- Iniciando proceso de carga de datos ---")
        
        roles_data = [
            (0, 'Guest'), (1, 'Administrator'), (2, 'Manager'), 
            (3, 'Assistant Manager'), (4, 'Operations'), 
            (5, 'Management'), (6, 'Finance')
        ]
        
        for r_id, r_name in roles_data:
            exist_role = Role.query.get(r_id)
            if not exist_role:
                nuevo_rol = Role(id=r_id, name=r_name)
                db.session.add(nuevo_rol)
                print(f"Agregando rol: {r_name}")
        
        db.session.commit()
        print("Roles sincronizados.")

        almacen = Location.query.get(1)
        if not almacen:
            nuevo_almacen = Location(
                id=1,
                name='Almacén Central',
                detailed_address='Inventario General / Sede Principal',
                state='Distrito Capital',
                phone='N/A',
                is_active=True
            )
            db.session.add(nuevo_almacen)
            db.session.commit()
            print("Almacén Central (Inventario General) creado con éxito.")
        else:
            print("El Almacén Central ya existe en el sistema.")

        try:
            db.session.execute(text("SELECT setval('locations_id_seq', (SELECT MAX(id) FROM locations));"))
            db.session.execute(text("SELECT setval('roles_id_seq', (SELECT MAX(id) FROM roles));"))
            db.session.commit()
            print("Contadores de base de datos sincronizados.")
        except Exception:
            db.session.rollback()

        email_admin = 'sistemat3.ph@gmail.com'
        user_exists = User.query.filter_by(email=email_admin).first()
        
        if not user_exists:
            admin = User(
                name='Mariuska Admin',
                email=email_admin,
                password_hash=generate_password_hash('ph12345'),
                role_id=1,
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()
            print(f"Usuario {email_admin} creado con éxito.")
            
            try:
                db.session.execute(text("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));"))
                db.session.commit()
            except Exception:
                db.session.rollback()
        else:
            print(f"El usuario {email_admin} ya existe en el sistema.")

if __name__ == '__main__':
    seed_database()