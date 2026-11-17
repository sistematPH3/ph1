"""La regla de vencimiento pertenece exclusivamente a la categoría.

Un producto/insumo del catálogo solo se vincula a una categoría (ProductType);
no maneja fecha ni regla de vencimiento propia. La categoría debe declarar de
forma obligatoria y excluyente:

  - Fecha manual en compra: requires_manual_date=True, sin días fijos.
  - Días de vida útil:      requires_manual_date=False, shelf_life_days >= 1.

Uso:
  .venv/Scripts/python -m pytest tests/inventory/test_category_expiration_control.py -q
"""

import os
import unittest

from sqlalchemy import create_engine, text

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
from app.models import Category, ProductType  # noqa: E402
from app.inventory.requests.categories_request import (  # noqa: E402
    validate_expiration_control,
)
from app.inventory.requests.products_request import validate_product_form  # noqa: E402
from app.inventory.services.category_service import CategoryService  # noqa: E402

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "templates", "inventory",
)


class CategoryExpirationValidatorTest(unittest.TestCase):
    """Contrato del validador de la regla de vencimiento de categorías."""

    def test_rechaza_categoria_sin_regla(self):
        errors, manual, days = validate_expiration_control({"name": "Secos"})
        self.assertIn("expiration_control", errors)
        self.assertIsNone(manual)
        self.assertIsNone(days)

    def test_rechaza_regla_desconocida(self):
        errors, _, _ = validate_expiration_control(
            {"name": "Secos", "expiration_control": "automatica"}
        )
        self.assertIn("expiration_control", errors)

    def test_acepta_regla_manual_sin_dias(self):
        errors, manual, days = validate_expiration_control(
            {"name": "Secos", "expiration_control": "manual", "shelf_life_days": "15"}
        )
        self.assertEqual(errors, {})
        self.assertTrue(manual)
        self.assertIsNone(days)

    def test_acepta_regla_por_dias(self):
        errors, manual, days = validate_expiration_control(
            {"name": "Secos", "expiration_control": "days", "shelf_life_days": "15"}
        )
        self.assertEqual(errors, {})
        self.assertFalse(manual)
        self.assertEqual(days, 15)

    def test_rechaza_dias_invalidos(self):
        for raw in ("", None, "0", "-3", "abc", "1.5"):
            with self.subTest(shelf_life_days=raw):
                errors, _, days = validate_expiration_control(
                    {"name": "Secos", "expiration_control": "days",
                     "shelf_life_days": raw}
                )
                self.assertIn("shelf_life_days", errors)
                self.assertIsNone(days)


class CategoryExpirationServiceTest(unittest.TestCase):
    """Persistencia de la regla en la categoría (ProductType)."""

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

    def tearDown(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    def _type(self):
        return ProductType.query.filter_by(name="Secos").one()

    def test_crea_categoria_manual(self):
        CategoryService.create_category(
            {"name": "Secos", "expiration_control": "manual"}
        )
        tipo = self._type()
        self.assertTrue(tipo.requires_manual_date)
        self.assertIsNone(tipo.shelf_life_days)
        # La categoría raíz queda creada y relacionada.
        self.assertIsNotNone(tipo.category_id)
        self.assertIsNotNone(db.session.get(Category, tipo.category_id))

    def test_crea_categoria_por_dias(self):
        CategoryService.create_category(
            {"name": "Secos", "expiration_control": "days", "shelf_life_days": "15"}
        )
        tipo = self._type()
        self.assertFalse(tipo.requires_manual_date)
        self.assertEqual(tipo.shelf_life_days, 15)

    def test_no_crea_categoria_sin_regla(self):
        with self.assertRaises(ValueError):
            CategoryService.create_category({"name": "Secos"})
        self.assertIsNone(ProductType.query.filter_by(name="Secos").first())

    def test_no_crea_categoria_con_dias_invalidos(self):
        with self.assertRaises(ValueError):
            CategoryService.create_category(
                {"name": "Secos", "expiration_control": "days",
                 "shelf_life_days": "0"}
            )
        self.assertIsNone(ProductType.query.filter_by(name="Secos").first())

    def test_actualiza_regla_y_limpia_dias_al_pasar_a_manual(self):
        CategoryService.create_category(
            {"name": "Secos", "expiration_control": "days", "shelf_life_days": "15"}
        )
        tipo = self._type()

        CategoryService.update_category(
            tipo.id, {"name": "Secos", "expiration_control": "manual"}
        )
        db.session.refresh(tipo)
        self.assertTrue(tipo.requires_manual_date)
        self.assertIsNone(tipo.shelf_life_days)

        CategoryService.update_category(
            tipo.id, {"name": "Secos", "expiration_control": "days",
                      "shelf_life_days": "30"}
        )
        db.session.refresh(tipo)
        self.assertFalse(tipo.requires_manual_date)
        self.assertEqual(tipo.shelf_life_days, 30)

    def test_actualizacion_sin_regla_no_altera_la_categoria(self):
        CategoryService.create_category(
            {"name": "Secos", "expiration_control": "manual"}
        )
        tipo = self._type()

        with self.assertRaises(ValueError):
            CategoryService.update_category(tipo.id, {"name": "Secos"})

        db.session.rollback()
        db.session.expire_all()
        tipo = self._type()
        self.assertTrue(tipo.requires_manual_date)


class ProductFormHasNoExpirationTest(unittest.TestCase):
    """El formulario de producto no debe volver a pedir vencimientos."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def _template(self, name):
        with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as fh:
            return fh.read()

    def test_formulario_de_producto_no_pide_vencimiento(self):
        template = self._template("product_form.html")
        self.assertNotIn("expiration-control-group", template)
        self.assertNotIn("Control de Vencimiento", template)
        self.assertNotIn('id="expiration_control_manual"', template)
        self.assertNotIn("Fecha de Vencimiento Primaria", template)
        self.assertNotIn('name="date_day"', template)

    def test_formulario_de_categoria_pide_la_regla_obligatoria(self):
        template = self._template("category_form.html")
        self.assertIn('name="expiration_control"', template)
        self.assertIn('value="manual"', template)
        self.assertIn('value="days"', template)
        self.assertEqual(template.count('name="expiration_control"'), 2)

    def test_validador_de_producto_ignora_campos_de_vencimiento(self):
        is_valid, errors, data = validate_product_form({
            "name": "Harina",
            "sku": "HAR-SIN-VENC",
            "product_type_id": "1",
            "unit_of_measure_select": "KG",
            "waste_limit": "2",
            "min_stock": "5",
            # Un cliente antiguo podría enviar estos campos: se ignoran.
            "expiration_control": "days",
            "shelf_life_days": "15",
            "expiration_date": "2027-12-15",
        })
        self.assertTrue(is_valid, errors)
        self.assertNotIn("expiration_control", data)
        self.assertNotIn("requires_manual_date", data)
        self.assertNotIn("shelf_life_days", data)
        self.assertNotIn("expiration_date", data)


if __name__ == "__main__":
    unittest.main()
