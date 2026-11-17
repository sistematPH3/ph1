"""Mensajes diferenciados del login (solicitud rechazada / correo no registrado).

El esquema no se modifica: el rechazo elimina al aspirante de `users` (el
correo queda libre para volver a registrarse) y deja constancia en
`audit_logs` con action='RECHAZO_SOLICITUD'. El login consulta ese rastro
solo cuando el correo no tiene cuenta.
"""
import os
import unittest

from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test",
)


def _asegurar_bd_pruebas():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not existe:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


_asegurar_bd_pruebas()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import AuditLog, Location, LoginAudit, Role, User  # noqa: E402
from app.models.security_model import user_locations  # noqa: E402
from app.security.repositories.user_management_repository import (  # noqa: E402
    UserManagementRepository,
)
from app.security.services.login_service import LoginService  # noqa: E402
from app.security.services.register_service import RegisterService  # noqa: E402

PASSWORD = "Prueba#1"
CORREO_RECHAZADO = "rechazado.login@prueba.test"
CORREO_INEXISTENTE = "nadie.login@prueba.test"
CORREO_ADMIN = "admin.mensajes@prueba.test"


class LoginMensajesTest(unittest.TestCase):

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
        self.client = self.app.test_client()
        self._limpiar()
        self.rol_guest = self._rol(0, "Guest")
        self.rol_admin = self._rol(1, "Administrator")
        self.sede = Location(name="Sede Mensajes Login", state="Caracas",
                             is_active=True)
        db.session.add(self.sede)
        db.session.flush()
        self.admin = User(
            name="Admin Mensajes",
            email=CORREO_ADMIN,
            password_hash=generate_password_hash(PASSWORD),
            role_id=self.rol_admin.id,
            is_active=True,
        )
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        self._limpiar()
        db.session.delete(db.session.get(Location, self.sede.id))
        db.session.commit()
        self.ctx.pop()

    # ------------------------------------------------------------ helpers --
    def _rol(self, role_id, nombre):
        rol = db.session.get(Role, role_id)
        if rol is None:
            rol = Role(id=role_id, name=nombre)
            db.session.add(rol)
            db.session.flush()
        return rol

    def _limpiar(self):
        correos = [CORREO_RECHAZADO, CORREO_INEXISTENTE, CORREO_ADMIN]
        usuarios = User.query.filter(User.email.in_(correos)).all()
        ids = [u.id for u in usuarios]
        # audit_logs y login_audit referencian users: se limpian primero.
        AuditLog.query.filter(
            AuditLog.action == "RECHAZO_SOLICITUD",
            AuditLog.changed_data["email"].astext.in_(correos),
        ).delete(synchronize_session=False)
        if ids:
            AuditLog.query.filter(AuditLog.user_id.in_(ids)).delete(
                synchronize_session=False)
            LoginAudit.query.filter(LoginAudit.user_id.in_(ids)).delete(
                synchronize_session=False)
            db.session.execute(
                user_locations.delete().where(user_locations.c.user_id.in_(ids))
            )
            for usuario in usuarios:
                usuario.locations = []
            db.session.flush()
            for usuario in usuarios:
                db.session.delete(usuario)
        db.session.commit()

    def _login(self, email, password=PASSWORD):
        return self.client.post(
            "/auth/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    def _rechazar(self, email):
        RegisterService.registrar_usuario("Persona Rechazada", email, PASSWORD)
        aspirante = User.query.filter_by(email=email).first()
        self.assertIsNotNone(aspirante, "El registro debe crear al aspirante")
        self.assertTrue(
            UserManagementRepository.delete_user(
                aspirante.id, responsible_user_id=self.admin.id),
            "El rechazo debe completarse",
        )

    # -------------------------------------------------------------- casos --
    def test_rechazo_deja_rastro_en_audit_logs(self):
        self._rechazar(CORREO_RECHAZADO)
        self.assertIsNone(User.query.filter_by(email=CORREO_RECHAZADO).first(),
                          "El rechazo borra al aspirante de users")
        rastro = AuditLog.query.filter_by(action="RECHAZO_SOLICITUD").all()
        self.assertTrue(
            any(r.changed_data.get("email") == CORREO_RECHAZADO
                for r in rastro),
            "El correo rechazado debe quedar en audit_logs",
        )
        self.assertEqual(rastro[0].affected_table, "users")

    def test_login_de_rechazado_informa_el_rechazo(self):
        self._rechazar(CORREO_RECHAZADO)
        respuesta = self._login(CORREO_RECHAZADO)
        cuerpo = respuesta.get_data(as_text=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("solicitud de registro fue rechazada", cuerpo)
        self.assertNotIn("no está registrado", cuerpo)

    def test_servicio_reporta_solicitud_rechazada(self):
        self._rechazar(CORREO_RECHAZADO)
        usuario, motivo = LoginService.autenticar(CORREO_RECHAZADO, PASSWORD)
        self.assertIsNone(usuario)
        self.assertEqual(motivo, "solicitud_rechazada")

    def test_rechazado_puede_volver_a_registrarse_sin_duplicado(self):
        self._rechazar(CORREO_RECHAZADO)
        RegisterService.registrar_usuario("Persona Nueva", CORREO_RECHAZADO,
                                          PASSWORD)
        nuevo = User.query.filter_by(email=CORREO_RECHAZADO).first()
        self.assertIsNotNone(nuevo, "El correo rechazado debe quedar libre")

    def test_registro_nuevo_manda_sobre_el_rechazo_anterior(self):
        self._rechazar(CORREO_RECHAZADO)
        RegisterService.registrar_usuario("Persona Nueva", CORREO_RECHAZADO,
                                          PASSWORD)
        usuario, motivo = LoginService.autenticar(CORREO_RECHAZADO, PASSWORD)
        self.assertEqual(motivo, "ok")
        self.assertTrue(usuario.is_guest)
        respuesta = self._login(CORREO_RECHAZADO)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("waiting-room", respuesta.headers["Location"])

    def test_correo_inexistente_invita_a_registrarse(self):
        cuerpo = self._login(CORREO_INEXISTENTE).get_data(as_text=True)
        self.assertIn("no está registrado", cuerpo)
        self.assertIn("Regístrate", cuerpo)

    def test_password_incorrecta_sigue_siendo_generica(self):
        cuerpo = self._login(CORREO_ADMIN, "Incorrecta#1").get_data(as_text=True)
        self.assertIn("erróneos", cuerpo)
        self.assertNotIn("no está registrado", cuerpo)


if __name__ == "__main__":
    unittest.main()
