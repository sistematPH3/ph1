from app import create_app
from app.extensions import db
from app.models.security_model import User, Role
from werkzeug.security import generate_password_hash

app = create_app()

def seed_database():
    with app.app_context():
        from app.models import inventory_model
        print("--- Iniciando proceso de carga de datos ---")
        
        # 1. Cargar Roles (Mantenemos intacta tu estructura original)
        roles_data = [
            (0, 'Guest'), (1, 'Administrator'), (2, 'Manager'), 
            (3, 'Assistant Manager'), (4, 'Operations'), 
            (5, 'Management'), (6, 'Finance')
        ] #
        
        for r_id, r_name in roles_data:
            exist_role = Role.query.get(r_id)
            if not exist_role:
                nuevo_rol = Role(id=r_id, name=r_name)
                db.session.add(nuevo_rol)
                print(f"Agregando rol: {r_name}")
        
        db.session.commit()
        print("✅ Roles sincronizados.")

        # 2. Cargar Categorías MACRO (Estructura de la Franquicia)
        macro_categorias = [
            "Carnes, Aves y Embutidos", 
            "Pescados y Mariscos", 
            "Lácteos y Huevos", 
            "Hortalizas y Frutas", 
            "Alimentos de Despensa",
            "Utensilios y Empaques",
            "Limpieza y Químicos"
        ]

        print("Sincronizando categorías macro...")
        for cat_name in macro_categorias:
            exist_cat = inventory_model.Category.query.filter_by(name=cat_name).first()
            if not exist_cat:
                nueva_categoria = inventory_model.Category(name=cat_name)
                db.session.add(nueva_categoria)
                print(f"Agregando categoría macro: {cat_name}")
        db.session.commit()

        # 3. Cargar TIPOS DE PRODUCTO (Reglas de vencimiento para la cocina)
        # Formato: (Nombre Subcategoría, Nombre Categoría Macro, Requiere Fecha Manual?, Días de Vida Útil)
        tipos_operativos = [
            # Carnes
            ("Embutidos y Carnes Curadas", "Carnes, Aves y Embutidos", True, None),
            ("Carnes y Aves Procesadas Congeladas", "Carnes, Aves y Embutidos", True, None),
            # Pescados
            ("Mariscos Congelados", "Pescados y Mariscos", True, None),
            ("Conservas de Mar", "Pescados y Mariscos", True, None),
            # Lácteos
            ("Quesos Madurados y Rallados", "Lácteos y Huevos", True, None),
            ("Lácteos Frescos", "Lácteos y Huevos", True, None),
            ("Huevos y Ovoproductos", "Lácteos y Huevos", True, None),
            # Perecederos frescos (Cálculos automáticos)
            ("Hortalizas Frescas", "Hortalizas Frutas", False, 10),  # Ej: Tomate ensalada
            ("Verduras de Hoja", "Hortalizas y Frutas", False, 4),    # Ej: Lechugas
            ("Frutas Frescas", "Hortalizas y Frutas", False, 7),       # Ej: Piña
            # Despensa / Secos
            ("Harinas y Premezclas", "Alimentos de Despensa", True, None),
            ("Condimentos y Especias", "Alimentos de Despensa", True, None),
            ("Aceites y Grasas", "Alimentos de Despensa", True, None),
            ("Salsas y Aderezos Listos", "Alimentos de Despensa", True, None),
            # No perecederos estrictos
            ("Cajas y Empaques", "Utensilios y Empaques", False, None),
            ("Químicos de Limpieza", "Limpieza y Químicos", False, None)
        ]

        print("Sincronizando tipos de productos operativos...")
        for type_name, macro_name, req_manual, shelf_days in tipos_operativos:
            # Buscamos la categoría macro correspondiente para obtener su ID
            macro_parent = inventory_model.Category.query.filter_by(name=macro_name).first()
            
            if macro_parent:
                exist_type = inventory_model.ProductType.query.filter_by(name=type_name).first()
                if not exist_type:
                    nuevo_tipo = inventory_model.ProductType(
                        name=type_name,
                        category_id=macro_parent.id,
                        requires_manual_date=req_manual,
                        shelf_life_days=shelf_days
                    )
                    db.session.add(nuevo_tipo)
                    print(f"Agregando tipo operativo: {type_name} -> [{macro_name}]")
        
        db.session.commit()
        print("✅ Categorías y tipos operativos parametrizados con éxito.")

        # 4. Cargar Usuario Administrador (Mantenemos intacta tu estructura original)
        email_admin = 'sistemat3.ph@gmail.com' #
        user_exists = User.query.filter_by(email=email_admin).first() #
        
        if not user_exists:
            admin = User(
                name='Mariuska Admin', #
                email=email_admin, #
                password_hash=generate_password_hash('ph12345'), #
                role_id=1, #
                is_active=True #
            )
            db.session.add(admin)
            db.session.commit()
            print(f"✅ Usuario {email_admin} creado con éxito.")
        else:
            print(f"ℹ️ El usuario {email_admin} ya existe en la base de datos.")

        print("--- Proceso finalizado ---")

if __name__ == '__main__':
    seed_database()