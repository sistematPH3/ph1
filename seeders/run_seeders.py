from app import create_app
from app.extensions import db
from app.models.security_model import User, Role
from app.models import Location, WasteType, AppParameter
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, text

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

        # Cuenta de fábrica. Debe quedar SIEMPRE en un estado que permita
        # iniciar sesión: si no existe se crea, y si existe pero su hash no
        # valida contra la contraseña de fábrica (hash de otro esquema, cadena
        # vacía o truncada) se restablece. Antes el seeder solo creaba cuando
        # el correo no aparecía: una fila con el hash roto o con el correo en
        # otra capitalización se quedaba para siempre sin poder entrar.
        email_admin = 'sistemat3.ph@gmail.com'
        password_admin = 'Ph12345.'
        user_exists = (User.query
                       .filter(func.lower(func.trim(User.email)) == email_admin)
                       .first())

        if not user_exists:
            admin = User(
                name='Sistema Admin',
                email=email_admin,
                password_hash=generate_password_hash(password_admin),
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
            reparado = False
            try:
                hash_valido = bool(user_exists.password_hash) and check_password_hash(
                    user_exists.password_hash, password_admin)
            except Exception:
                hash_valido = False

            if not hash_valido:
                user_exists.password_hash = generate_password_hash(password_admin)
                reparado = True
                print(f"Hash inválido para {email_admin}: restablecido a la contraseña de fábrica.")

            if not user_exists.is_active:
                user_exists.is_active = True
                reparado = True
                print(f"Usuario {email_admin} reactivado.")

            if reparado:
                db.session.commit()

            print(f"El usuario {email_admin} ya existe en el sistema.")

        seed_waste_types()
        seed_app_parameters()


def seed_waste_types():
    """Siembra los 7 tipos de merma (el catálogo arranca vacío)."""
    tipos = [
        # (code, name, description, severity, requires_approval, applies_central)
        ('VENCIDO',            'Vencido / expirado',
         'Producto que paso su fecha por mala rotacion FEFO',
         'MEDIA', False, False),
        ('DANADO_FISICO',      'Dañado físico',
         'Caja o producto que se cae y se rompe / danifica',
         'MEDIA', False, False),
        ('ERROR_PREPARACION',  'Error de preparación',
         'Pizza quemada u otro error en hora pico',
         'MEDIA', False, False),
        ('OVERPRODUCTION',     'Sobreproducción',
         'Masa/salsas que pasaron su tiempo de vida util',
         'MEDIA', False, False),
        ('RECORTE_EXCESIVO',   'Recorte excesivo',
         'Pimenton/cebolla descartados por mal corte (mise en place)',
         'BAJA', False, False),
        ('TEMPERATURA',        'Ruptura de cadena de frío',
         'Falla en la cava; carne fuera de temperatura sanitaria',
         'CRITICA', True, True),
        ('ROBO_SOSPECHA',      'Sospecha de robo/extravío',
         'Faltan productos que no figuran en ventas ni traslados',
         'CRITICA', True, True),
    ]

    for code, name, desc, severity, requires_approval, applies_central in tipos:
        exist = WasteType.query.filter_by(code=code).first()
        if not exist:
            db.session.add(WasteType(
                code=code, name=name, description=desc,
                severity=severity, requires_approval=requires_approval,
                applies_central=applies_central, is_active=True,
            ))
            print(f"Agregando tipo de merma: {code}")
    db.session.commit()


def seed_app_parameters():
    """Siembra las 2 reglas de TIEMPO del control de mermas (app_parameters)."""
    parametros = [
        ('WASTE_TIME_TOLERANCE',   '1.5', 'Factor de margen de la regla de tiempo'),
        ('WASTE_BASE_PERIOD_DAYS', '7',   'Periodo base si no hay merma previa'),
    ]
    for key, value, desc in parametros:
        exist = AppParameter.query.filter_by(key=key).first()
        if not exist:
            db.session.add(AppParameter(key=key, value=value, description=desc))
            print(f"Agregando parametro: {key}")
    db.session.commit()


if __name__ == '__main__':
    seed_database()