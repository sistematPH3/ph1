# =============================================================================
# REGRESIÓN: ACTIVACIÓN AUTOMÁTICA EN EL ALTA INICIAL CON SEDES ACTIVAS
# -----------------------------------------------------------------------------
# Regla de negocio: un usuario nuevo que recibe rol y sedes activas en su
# configuración inicial debe quedar activo de inmediato. Las reglas previas se
# mantienen: sin sedes activas no se activa, y a un usuario ya desactivado a
# mano (que ya tenía sedes) no se le reactiva al reasignarle sedes.
# =============================================================================

import os
import unittest
import uuid

from sqlalchemy import create_engine, text

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

from flask_login import login_user  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models import Location, Role, User, UserAudit  # noqa: E402
from app.security.repositories.user_management_repository import (  # noqa: E402
    UserManagementRepository,
)
from app.security.services.staff_service import StaffService  # noqa: E402


class ActivacionAltaInicialTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls.rol_admin = cls._rol("Administrator")
        cls.rol_ops = cls._rol("Operations")
        # El rol 0 (invitado) representa la solicitud pendiente de aprobación.
        cls.rol_guest_creado = db.session.get(Role, 0) is None
        if cls.rol_guest_creado:
            db.session.add(Role(id=0, name="Guest"))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        if cls.rol_guest_creado:
            try:
                Role.query.filter(Role.id == 0).delete(synchronize_session=False)
                db.session.commit()
            except Exception:
                db.session.rollback()
        db.session.remove()
        cls.ctx.pop()

    @classmethod
    def _rol(cls, nombre):
        rol = Role.query.filter_by(name=nombre).first()
        if rol is None:
            rol = Role(name=nombre)
            db.session.add(rol)
            db.session.flush()
        return rol

    def setUp(self):
        sufijo = uuid.uuid4().hex[:8]
        self.email_base = f"alta-{sufijo}"
        self.sede_activa = Location(
            name=f"SEDE-ACTIVA-{sufijo}", is_active=True, state="Caracas"
        )
        self.sede_inactiva = Location(
            name=f"SEDE-INACTIVA-{sufijo}", is_active=False, state="Caracas"
        )
        self.admin = User(
            name=f"Admin {sufijo}",
            email=f"{self.email_base}-admin@prueba.test",
            password_hash="x",
            role=self.rol_admin,
            is_active=True,
        )
        db.session.add_all([self.sede_activa, self.sede_inactiva, self.admin])
        db.session.commit()

    def tearDown(self):
        usuarios = User.query.filter(
            User.email.like(f"{self.email_base}%")
        ).all()
        ids_usuarios = [u.id for u in usuarios]
        if ids_usuarios:
            UserAudit.query.filter(
                (UserAudit.target_user_id.in_(ids_usuarios))
                | (UserAudit.responsible_user_id.in_(ids_usuarios))
            ).delete(synchronize_session=False)
            # Limpiamos la tabla intermedia antes de borrar a los usuarios.
            for usuario in usuarios:
                usuario.locations = []
            db.session.flush()
            for usuario in usuarios:
                db.session.delete(usuario)
        Location.query.filter(
            Location.name.in_([self.sede_activa.name, self.sede_inactiva.name])
        ).delete(synchronize_session=False)
        db.session.commit()

    def _usuario(self, role, sedes=(), activo=False):
        usuario = User(
            name=f"Usuario {uuid.uuid4().hex[:6]}",
            email=f"{self.email_base}-{uuid.uuid4().hex[:6]}@prueba.test",
            password_hash="x",
            role=role,
            is_active=activo,
        )
        usuario.locations = list(sedes)
        db.session.add(usuario)
        db.session.commit()
        return usuario

    # --- Flujo de aprobación (usuario nuevo) --------------------------------

    def test_aprobacion_con_sede_activa_deja_al_usuario_activo(self):
        pendiente = User(
            name="Pendiente",
            email=f"{self.email_base}-pendiente@prueba.test",
            password_hash="x",
            role_id=0,
            is_active=False,
        )
        db.session.add(pendiente)
        db.session.commit()

        UserManagementRepository.update_user_status(
            pendiente.id, self.rol_ops.id, [self.sede_activa.id]
        )

        db.session.refresh(pendiente)
        self.assertTrue(pendiente.is_active)

    def test_aprobacion_sin_sedes_activas_mantiene_inactivo(self):
        pendiente = User(
            name="Pendiente",
            email=f"{self.email_base}-pendiente2@prueba.test",
            password_hash="x",
            role_id=0,
            is_active=False,
        )
        db.session.add(pendiente)
        db.session.commit()

        UserManagementRepository.update_user_status(
            pendiente.id, self.rol_ops.id, [self.sede_inactiva.id]
        )

        db.session.refresh(pendiente)
        self.assertFalse(pendiente.is_active)

    def test_aprobacion_de_administrador_sin_sedes_lo_activa(self):
        pendiente = User(
            name="Pendiente Admin",
            email=f"{self.email_base}-pendiente3@prueba.test",
            password_hash="x",
            role_id=0,
            is_active=False,
        )
        db.session.add(pendiente)
        db.session.commit()

        UserManagementRepository.update_user_status(
            pendiente.id, self.rol_admin.id, []
        )

        db.session.refresh(pendiente)
        self.assertTrue(pendiente.is_active)

    # --- Edición de personal (primera asignación de sedes) ------------------

    def _editar(self, usuario, sedes, rol=None):
        with self.app.test_request_context():
            login_user(self.admin)
            return StaffService.actualizar_usuario(
                usuario.id,
                {
                    "email": usuario.email,
                    "locations": [loc.id for loc in sedes],
                    "role_id": str((rol or usuario.role_id)),
                },
            )

    def test_primera_asignacion_de_sedes_activas_activa_al_usuario(self):
        usuario = self._usuario(self.rol_ops, sedes=(), activo=False)

        exito, _ = self._editar(usuario, [self.sede_activa])

        self.assertTrue(exito)
        db.session.refresh(usuario)
        self.assertTrue(usuario.is_active)

    def test_primera_asignacion_solo_de_sede_inactiva_no_lo_activa(self):
        usuario = self._usuario(self.rol_ops, sedes=(), activo=False)

        exito, _ = self._editar(usuario, [self.sede_inactiva])

        self.assertTrue(exito)
        db.session.refresh(usuario)
        self.assertFalse(usuario.is_active)

    def test_usuario_desactivado_a_mano_no_se_reactiva_al_reasignar_sedes(self):
        usuario = self._usuario(
            self.rol_ops, sedes=[self.sede_activa], activo=False
        )

        exito, _ = self._editar(usuario, [self.sede_activa])

        self.assertTrue(exito)
        db.session.refresh(usuario)
        self.assertFalse(usuario.is_active)


if __name__ == "__main__":
    unittest.main()
