import os
import unittest

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
from app.models import Category, Location, Product, ProductType, Role, User

PASSWORD = "Prueba#1"
ADMIN_EMAIL = "admin.flash@prueba.test"


class FlashIsolationTest(unittest.TestCase):

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
        self.guest_role = Role(id=0, name="Guest")
        db.session.add_all([self.role, self.guest_role])
        db.session.flush()
        self.admin = User(
            name="Admin Flash",
            email=ADMIN_EMAIL,
            password_hash=generate_password_hash(PASSWORD),
            role_id=self.role.id,
            is_active=True,
        )
        self.categoria = Category(name="Categoría base")
        db.session.add_all([self.admin, self.categoria])
        db.session.flush()
        self.tipo = ProductType(
            name="Tipo base",
            category_id=self.categoria.id,
            requires_manual_date=True,
        )
        db.session.add(self.tipo)
        db.session.flush()
        self.producto = Product(
            name="Insumo base",
            sku="BASE-1",
            product_type_id=self.tipo.id,
            unit_of_measure="KG",
            waste_limit=1,
            min_stock=1,
            is_active=True,
        )
        db.session.add(self.producto)
        db.session.commit()
        self.client = self.app.test_client()
        response = self.client.post(
            "/auth/login",
            data={"email": ADMIN_EMAIL, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.urls = [
            "/inventory/categories",
            "/inventory/categories/create",
            "/inventory/products",
            "/inventory/products/create",
            f"/inventory/products/edit/{self.producto.id}",
        ]

    def tearDown(self):
        db.session.rollback()
        self._limpiar()
        self.ctx.pop()

    def _limpiar(self):
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()

    def _pendiente(self, email):
        usuario = User(
            name="Aspirante",
            email=email,
            password_hash="x",
            role_id=self.guest_role.id,
            is_active=False,
        )
        db.session.add(usuario)
        db.session.commit()
        return usuario

    def _datos_producto(self, nombre, sku, unidad="KG"):
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

    def _assert_ausente_en_vistas(self, generar, mensaje):
        for url in self.urls:
            with self.subTest(url=url):
                respuesta = generar()
                self.assertEqual(respuesta.status_code, 302)
                html = self.client.get(url).get_data(as_text=True)
                self.assertNotIn(mensaje, html)

    def test_flash_de_sede_se_muestra_en_sedes_y_no_en_inventario(self):
        creada = self.client.post("/logistics/locations", data={
            "name": "Pizza Hut (Las Mercedes)",
            "state": "Miranda",
            "address": "Av. Principal",
            "phone": "04141234567",
        })
        self.assertEqual(creada.status_code, 200)
        self.assertNotIn("Sede registrada exitosamente.",
                         creada.get_data(as_text=True))
        self.assertNotIn("Sede registrada exitosamente.",
                         self.client.get("/inventory/categories").get_data(as_text=True))

        error = self.client.post("/logistics/locations/edit/999999")
        self.assertEqual(error.status_code, 302)
        self.assertIn("Sede no encontrada",
                      self.client.get("/sedes").get_data(as_text=True))

    def test_flash_de_error_de_sede_no_se_filtra_a_inventario(self):
        self._assert_ausente_en_vistas(
            lambda: self.client.post("/logistics/locations/edit/999999"),
            "Sede no encontrada",
        )

    def test_flash_de_aprobacion_de_usuario_no_se_filtra(self):
        contador = {"n": 0}

        def aprobar():
            contador["n"] += 1
            usuario = self._pendiente(f"aprobar{contador['n']}@prueba.test")
            return self.client.post(
                f"/auth/admin/approve/{usuario.id}",
                data={"role_id": "1"},
            )

        self._assert_ausente_en_vistas(
            aprobar,
            "Usuario aprobado, sedes asignadas y activado correctamente",
        )

    def test_flash_de_rechazo_de_usuario_no_se_filtra(self):
        contador = {"n": 0}

        def rechazar():
            contador["n"] += 1
            usuario = self._pendiente(f"rechazar{contador['n']}@prueba.test")
            return self.client.post(f"/auth/admin/reject/{usuario.id}")

        self._assert_ausente_en_vistas(
            rechazar,
            "La solicitud ha sido rechazada y eliminada de la base de datos",
        )

    def test_flash_de_usuario_se_muestra_en_solicitudes(self):
        usuario = self._pendiente("pendiente.visible@prueba.test")
        respuesta = self.client.post(
            f"/auth/admin/approve/{usuario.id}",
            data={"role_id": "1"},
            follow_redirects=True,
        )
        self.assertIn(
            "Usuario aprobado, sedes asignadas y activado correctamente",
            respuesta.get_data(as_text=True),
        )

    def test_flash_propio_de_categoria_se_muestra(self):
        respuesta = self.client.post(
            "/inventory/categories/create",
            data={"name": "Categoría flash", "expiration_control": "manual"},
            follow_redirects=True,
        )
        self.assertIn("Categoría registrada exitosamente.",
                      respuesta.get_data(as_text=True))

        error = self.client.get("/inventory/categories/edit/999999",
                                follow_redirects=True)
        self.assertIn("Categoría no encontrada.",
                      error.get_data(as_text=True))

    def test_flash_propio_de_insumo_se_muestra(self):
        respuesta = self.client.post(
            "/inventory/products/create",
            data=self._datos_producto("Insumo flash", "FLASH-1"),
            follow_redirects=True,
        )
        self.assertIn("Insumo registrado exitosamente.",
                      respuesta.get_data(as_text=True))

        error = self.client.get("/inventory/products/edit/999999",
                                follow_redirects=True)
        self.assertIn("El insumo que intenta editar no existe.",
                      error.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
