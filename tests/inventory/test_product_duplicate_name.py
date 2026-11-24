"""Unicidad del nombre de los insumos.

Un insumo no puede repetirse por nombre en el catálogo, sin importar
mayúsculas/minúsculas ni espacios al inicio o al final. La regla se aplica en
tres capas: validador del formulario, servicio y restricción de la base de
datos.

Uso:
  .venv/Scripts/python -m pytest tests/inventory/test_product_duplicate_name.py -q
"""

import os
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
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

from app import create_app, db  # noqa: E402
from app.models import Category, Product, ProductType, Role, User  # noqa: E402
from app.inventory.requests.products_request import validate_product_form  # noqa: E402
from app.inventory.services.products_service import ProductService  # noqa: E402

MENSAJE_DUPLICADO = "Ya existe un insumo registrado con este nombre."


def _formulario(name, sku="HUE-2", product_type_id="1"):
    return {
        "name": name,
        "sku": sku,
        "product_type_id": product_type_id,
        "unit_of_measure_select": "UN",
        "waste_limit": "1",
        "min_stock": "5",
    }


class ProductDuplicateNameTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        self.user = User(name="Admin Dup", email="admin@dup.test",
                         password_hash="x", role_id=role.id)
        db.session.add(self.user)
        db.session.flush()

        categoria = Category(name="Perecederos")
        db.session.add(categoria)
        db.session.flush()
        self.tipo = ProductType(name="Huevos", category_id=categoria.id)
        db.session.add(self.tipo)
        db.session.flush()

        self.existente = Product(
            name="Huevos Perecederos",
            sku="HUE-1",
            product_type_id=self.tipo.id,
            unit_of_measure="UN",
            waste_limit=1,
            min_stock=5,
            is_active=True,
        )
        db.session.add(self.existente)
        db.session.commit()
        self.tipo_id = str(self.tipo.id)

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # Validador del formulario
    # ------------------------------------------------------------------
    def test_rechaza_nombre_duplicado(self):
        is_valid, errors, _ = validate_product_form(
            _formulario("Huevos Perecederos", product_type_id=self.tipo_id)
        )
        self.assertFalse(is_valid)
        self.assertEqual(errors.get("name"), MENSAJE_DUPLICADO)

    def test_rechaza_duplicado_sin_importar_mayusculas(self):
        is_valid, errors, _ = validate_product_form(
            _formulario("  huevos perecederos  ", product_type_id=self.tipo_id)
        )
        self.assertFalse(is_valid)
        self.assertEqual(errors.get("name"), MENSAJE_DUPLICADO)

    def test_permite_conservar_el_mismo_nombre_al_editar(self):
        is_valid, errors, _ = validate_product_form(
            _formulario("Huevos Perecederos", sku="HUE-1",
                        product_type_id=self.tipo_id),
            current_product_id=self.existente.id,
        )
        self.assertTrue(is_valid, errors)

    # ------------------------------------------------------------------
    # Servicio (creación y edición)
    # ------------------------------------------------------------------
    def test_servicio_no_crea_duplicado(self):
        with self.assertRaises(ValueError) as ctx:
            ProductService.create_product(
                _formulario("huevos perecederos", product_type_id=self.tipo_id)
            )
        self.assertEqual(str(ctx.exception), MENSAJE_DUPLICADO)
        self.assertEqual(
            Product.query.filter_by(sku="HUE-2").first(), None
        )

    def test_servicio_no_permite_renombrar_a_un_nombre_existente(self):
        otro = Product(
            name="Huevos Criollos",
            sku="HUE-3",
            product_type_id=self.tipo.id,
            unit_of_measure="UN",
            waste_limit=1,
            min_stock=5,
            is_active=True,
        )
        db.session.add(otro)
        db.session.commit()

        with self.assertRaises(ValueError) as ctx:
            ProductService.update_product(
                otro.id,
                _formulario("Huevos Perecederos", sku="HUE-3",
                            product_type_id=self.tipo_id),
            )
        self.assertEqual(str(ctx.exception), MENSAJE_DUPLICADO)

    # ------------------------------------------------------------------
    # Endpoint de consulta en tiempo real
    # ------------------------------------------------------------------
    def _client(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(self.user.id)
            session["_fresh"] = True
        return client

    def test_endpoint_detecta_nombre_duplicado(self):
        response = self._client().get(
            "/inventory/products/check-name",
            query_string={"name": "huevos perecederos"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["exists"])

    def test_endpoint_permite_nombre_nuevo(self):
        response = self._client().get(
            "/inventory/products/check-name",
            query_string={"name": "Huevos Criollos"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["exists"])

    def test_endpoint_excluye_el_propio_insumo_al_editar(self):
        response = self._client().get(
            "/inventory/products/check-name",
            query_string={"name": "Huevos Perecederos",
                          "exclude_id": self.existente.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["exists"])

    # ------------------------------------------------------------------
    # Restricción de base de datos
    # ------------------------------------------------------------------
    def test_base_de_datos_rechaza_nombre_duplicado(self):
        db.session.add(Product(
            name="Huevos Perecederos",
            sku="HUE-4",
            unit_of_measure="UN",
            min_stock=5,
        ))
        with self.assertRaises(IntegrityError):
            db.session.flush()
        db.session.rollback()


if __name__ == "__main__":
    unittest.main()
