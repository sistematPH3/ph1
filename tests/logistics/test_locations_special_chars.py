import os
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test",
)


def _ensure_test_database_exists():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_ensure_test_database_exists()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db
from app.models import Location, Role, User
from app.logistics.requests.locations_validators import LayoutValidators

PASSWORD = "Prueba#1"
ADMIN_EMAIL = "admin.sedes@prueba.test"
VALID_PHONE = "04141234567"


class LocationsSpecialCharsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self._limpiar()
        self.role = Role(id=1, name="Administrator")
        db.session.add(self.role)
        db.session.flush()
        self.admin = User(
            name="Admin Sedes",
            email=ADMIN_EMAIL,
            password_hash=generate_password_hash(PASSWORD),
            role_id=self.role.id,
            is_active=True,
        )
        db.session.add(self.admin)
        db.session.commit()
        self.client = self.app.test_client()
        response = self.client.post(
            "/auth/login",
            data={"email": ADMIN_EMAIL, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        db.session.rollback()
        self._limpiar()
        self.ctx.pop()

    def _limpiar(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()

    def _form(self, name, phone=VALID_PHONE):
        return {
            "name": name,
            "state": "Miranda",
            "address": "Av. Principal, Local 4",
            "phone": phone,
        }

    def test_crear_sede_con_parentesis_y_numeros(self):
        name = "Pizza Hut (Las Mercedes)"
        response = self.client.post("/logistics/locations", data=self._form(name))
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-success="true"',
                      response.get_data(as_text=True))
        sede = Location.query.filter_by(name=name).one()
        self.assertEqual(sede.state, "Miranda")
        self.assertEqual(sede.phone, VALID_PHONE)
        self.assertTrue(sede.is_active)

    def test_editar_sede_con_guiones_y_numeros(self):
        sede = Location(
            name="Pizza Hut Sambil",
            state="Carabobo",
            detailed_address="Nivel 2",
            phone=VALID_PHONE,
            is_active=True,
        )
        db.session.add(sede)
        db.session.commit()
        new_name = "Pizza Hut - Sambil 2"
        response = self.client.post(
            f"/logistics/locations/edit/{sede.id}",
            data=self._form(new_name),
        )
        self.assertEqual(response.status_code, 200)
        db.session.refresh(sede)
        self.assertEqual(sede.name, new_name)
        self.assertEqual(sede.state, "Miranda")

    def test_rechaza_caracteres_peligrosos_en_creacion(self):
        nombres = [
            "Sede <script>alert(1)</script>",
            "Sede @ Centro",
            "Sede #1",
            "Sede $ Dollar",
        ]
        for nombre in nombres:
            with self.subTest(nombre=nombre):
                response = self.client.post(
                    "/logistics/locations", data=self._form(nombre)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("caracteres inválidos",
                              response.get_data(as_text=True))
                self.assertIsNone(
                    Location.query.filter_by(name=nombre).first()
                )

    def test_rechaza_caracteres_peligrosos_en_edicion(self):
        sede = Location(
            name="Sede Original",
            state="Aragua",
            detailed_address="Calle 1",
            phone=VALID_PHONE,
            is_active=True,
        )
        db.session.add(sede)
        db.session.commit()
        response = self.client.post(
            f"/logistics/locations/edit/{sede.id}",
            data=self._form("Sede <script>"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("caracteres inválidos", response.get_data(as_text=True))
        db.session.refresh(sede)
        self.assertEqual(sede.name, "Sede Original")

    def test_endpoint_check_name_acepta_caracteres_especiales(self):
        name = "Pizza Hut (Las Mercedes)"
        disponible = self.client.post("/logistics/check-name", json={"name": name})
        self.assertEqual(disponible.status_code, 200)
        self.assertTrue(disponible.get_json()["available"])

        db.session.add(Location(
            name=name,
            state="Miranda",
            detailed_address="Av. Principal",
            phone=VALID_PHONE,
            is_active=True,
        ))
        db.session.commit()

        ocupado = self.client.post("/logistics/check-name", json={"name": name})
        self.assertFalse(ocupado.get_json()["available"])

        otro = self.client.post(
            "/logistics/check-name", json={"name": "Pizza Hut - Sambil 2"}
        )
        self.assertTrue(otro.get_json()["available"])

    def test_regex_backend_y_frontend_coinciden(self):
        esperado = r"^[a-zA-Z0-9 áéíóúÁÉÍÓÚñÑüÜ.()\-]*$"
        raiz = Path(__file__).resolve().parents[2]
        backend = (raiz / "app/logistics/requests/locations_validators.py").read_text(
            encoding="utf-8"
        )
        crear = (raiz / "app/static/js/logistics/register_location.js").read_text(
            encoding="utf-8"
        )
        editar = (raiz / "app/static/js/logistics/edit_location.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(esperado, backend)
        self.assertIn(f"const regex = /{esperado}/;", crear)
        self.assertIn(f"const regex = /{esperado}/;", editar)
        self.assertIsNotNone(LayoutValidators.validate_characters)


if __name__ == "__main__":
    unittest.main()
