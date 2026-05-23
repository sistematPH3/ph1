from app import create_app
from app.extensions import db
# ⚠️ Quitamos la importación de User y Role de aquí arriba
from werkzeug.security import generate_password_hash

app = create_app()

def seed_database():
    with app.app_context():
        
        from app.models.security_model import User, Role

        print("--- Iniciando proceso de carga de datos ---")
        
        # 1. Cargar Roles
        roles_data = [
            (0, 'Guest'), (1, 'Administrator'), (2, 'Manager'), 
            (3, 'Assistant Manager'), (4, 'Operations'), 
            (5, 'Audit'), (6, 'Management'), (7, 'Finance')
        ]
        
        for r_id, r_name in roles_data:
            exist_role = Role.query.get(r_id)
            if not exist_role:
                nuevo_rol = Role(id=r_id, name=r_name)
                db.session.add(nuevo_rol)
                print(f"Agregando rol: {r_name}")
        
        db.session.commit()
        print("✅ Roles sincronizados.")

        # 2. Cargar Usuario Administrador
        email_admin = 'sistemat3.ph@gmail.com'
        user_exists = User.query.filter_by(email=email_admin).first()
        
        if not user_exists:
            admin = User(
                name='Mariuska Admin',
                email=email_admin,
                password_hash=generate_password_hash('ph12345'),
                role_id=1, # Referencia a Administrator
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()
            print(f"✅ Usuario {email_admin} creado con éxito.")
        else:
            print(f"ℹ️ El usuario {email_admin} ya existe en la base de datos.")

        print("--- Proceso finalizado ---")

if __name__ == '__main__':
    seed_database()