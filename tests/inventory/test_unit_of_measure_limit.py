import os
import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
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
from app.models import Category, Product, ProductType, Role, User
from app.inventory.requests.products_request import validate_product_form

PASSWORD = "Prueba#1"
ADMIN_EMAIL = "admin.unidades@prueba.test"


class UnitOfMeasureLimitTest(unittest.TestCase):

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
            name="Admin Unidades",
            email=ADMIN_EMAIL,
            password_hash=generate_password_hash(PASSWORD),
            role_id=self.role.id,
            is_active=True,
        )
        self.categoria = Category(name="Insumos de prueba")
        db.session.add_all([self.admin, self.categoria])
        db.session.flush()
        self.tipo = ProductType(
            name="Abarrotes",
            category_id=self.categoria.id,
            requires_manual_date=True,
        )
        db.session.add(self.tipo)
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

    def _datos(self, nombre, sku, unidad):
        return {
            "name": nombre,
            "sku": sku,
            "product_type_id": str(self.tipo.id),
            "unit_of_measure_select": "OTHER",
            "unit_of_measure_custom": unidad,
            "technical_description": "",
            "waste_limit": "1",
            "min_stock": "1",
        }

    def test_crear_con_unidad_corta_y_con_exactamente_100_caracteres(self):
        corta = "Caja de cartón de 30 unidades"
        larga = "C" * 100
        response = self.client.post(
            "/inventory/products/create",
            data=self._datos("Insumo corto", "UNI-1", corta),
        )
        self.assertEqual(response.status_code, 302)
        producto_corto = Product.query.filter_by(sku="UNI-1").one()
        self.assertEqual(producto_corto.unit_of_measure, corta)
        self.assertEqual(len(producto_corto.unit_of_measure), 29)

        response = self.client.post(
            "/inventory/products/create",
            data=self._datos("Insumo largo", "UNI-2", larga),
        )
        self.assertEqual(response.status_code, 302)
        producto_largo = Product.query.filter_by(sku="UNI-2").one()
        self.assertEqual(producto_largo.unit_of_measure, larga)
        self.assertEqual(len(producto_largo.unit_of_measure), 100)

    def test_editar_unidad_a_cadena_larga(self):
        producto = Product(
            name="Insumo editable",
            sku="UNI-3",
            product_type_id=self.tipo.id,
            unit_of_measure="Caja de cartón de 30 unidades",
            waste_limit=1,
            min_stock=1,
            is_active=True,
        )
        db.session.add(producto)
        db.session.commit()
        nueva = "Bolsas selladas de 50 unidades por caja de despacho"
        self.assertGreaterEqual(len(nueva), 50)
        self.assertLessEqual(len(nueva), 100)
        response = self.client.post(
            f"/inventory/products/edit/{producto.id}",
            data=self._datos(producto.name, producto.sku, nueva),
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(producto)
        self.assertEqual(producto.unit_of_measure, nueva)

    def test_rechaza_101_caracteres_sin_guardar(self):
        response = self.client.post(
            "/inventory/products/create",
            data=self._datos("Insumo inválido", "UNI-4", "X" * 101),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("La unidad no puede exceder los 100 caracteres.",
                      response.get_data(as_text=True))
        self.assertIsNone(Product.query.filter_by(sku="UNI-4").first())

    def test_validador_rechaza_101_caracteres(self):
        valido, errores, _ = validate_product_form(
            self._datos("Insumo validador", "UNI-5", "Y" * 101)
        )
        self.assertFalse(valido)
        self.assertEqual(
            errores["unit_of_measure"],
            "La unidad no puede exceder los 100 caracteres.",
        )

    def test_modelo_y_columna_fisica_soportan_100_caracteres(self):
        self.assertEqual(Product.unit_of_measure.type.length, 100)
        longitud = db.session.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name='products' AND column_name='unit_of_measure'"
        )).scalar()
        self.assertEqual(longitud, 100)

    def test_migracion_alembic_tiene_una_sola_cabeza(self):
        config = Config()
        config.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parents[2] / "migrations"),
        )
        script = ScriptDirectory.from_config(config)
        self.assertEqual(script.get_heads(), ["b3e8f1a72c94"])
        self.assertEqual(script.get_bases(), ["7c0cb8c45047"])
        revision = script.get_revision("b3e8f1a72c94")
        self.assertEqual(revision.down_revision, "9f3a1c2d4e5b")


if __name__ == "__main__":
    unittest.main()
