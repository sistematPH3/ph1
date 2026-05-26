from app import create_app
from app.extensions import db
from app.models.security_model import User, Role
from werkzeug.security import generate_password_hash

app = create_app()

def seed_database():
    with app.app_context():
        from app.models import inventory_model
        print("--- Iniciando proceso de carga de datos ---")
        
        # 1. Cargar Roles
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
        print("✅ Roles sincronizados.")

        # 2. Cargar listado de Categorias de Productos

        categorias_data = ["Secos", "Lácteos", "Embutidos", "Vegetales Frescos", "Salsas y Líquidos", "Utensilios y Empaques"]

        print("Sincronizando categorías de productos...")
        for cat_name in categorias_data:
            
            exist_cat = inventory_model.Category.query.filter_by(name=cat_name).first()
            if not exist_cat:
                nueva_categoria = inventory_model.Category(name=cat_name)
                db.session.add(nueva_categoria)
                print(f"Agregando categoría: {cat_name}")

        db.session.commit()
        print("✅ Categorías parametrizadas con éxito.")

        # 2. Cargar Usuario Administrador[cite: 1]
        email_admin = 'sistemat3.ph@gmail.com'
        user_exists = User.query.filter_by(email=email_admin).first()
        
        if not user_exists:
            admin = User(
                name='Mariuska Admin',
                email=email_admin,
                password_hash=generate_password_hash('ph12345'),
                role_id=1, # Referencia a Administrator[cite: 1]
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