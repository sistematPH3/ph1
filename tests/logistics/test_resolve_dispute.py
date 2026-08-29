# =============================================================================
# PRUEBA AUTOMÁTICA DEL SERVICIO DE RESOLUCIÓN DE DISPUTAS
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) FALTANTE aceptado: si van 10 y llegan 8, al resolver la disputa la sede
#      destino queda con los 8 conformes y la sede origen recupera los 2 que
#      faltaron (se considera mercancía que nunca salió).
#   2) RECHAZO POR ESPACIO: si la carga llegó completa pero se rechazó, NO se
#      acredita nada en destino y se crea un traslado de retorno automático.
#
# Cómo funciona:
#   - Usa una base de datos DE PRUEBA (ph_test), NUNCA tu base real (ph).
#   - La crea sola si no existe y borra los datos entre prueba y prueba.
#   - Para ejecutarla, para en la carpeta ph1:
#       .\.venv\Scripts\python.exe -m unittest tests/test_resolve_dispute.py -v
# =============================================================================

import os
import unittest

from sqlalchemy import create_engine, text

# Base de datos de pruebas (puedes cambiar la URL con una variable TEST_DATABASE_URL).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:12345@localhost:5432/ph_test"
)


def _ensure_test_database_exists():
    """Crea la base ph_test si aún no existe (conexión al motor postgres)."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='ph_test'")
        ).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE "ph_test"'))
    engine.dispose()


# IMPORTANTE: esto DEBE correr antes de importar la app, porque la app lee la
# variable DATABASE_URL en el arranque. Apuntamos a la base de pruebas.
_ensure_test_database_exists()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import create_app, db
from app.models import AuditLog, Inventory, Location, Movement, MovementDetail, Product, Role, User
from app.logistics.services.movement_dispute_service import resolve_dispute


class ResolveDisputeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Una sola vez: crea la app y las tablas en ph_test."""
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        with cls.app.app_context():
            db.drop_all()
            db.create_all()

    def setUp(self):
        """Cada prueba arranca con la tienda abierta (contexto) y sin datos."""
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        """Cada prueba termina borrando TODO lo que se creó (base limpia)."""
        db.session.rollback()  # Si la prueba falló a mitad, salimos del mal estado.
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        self.ctx.pop()

    # =========================================================================
    # AYUDA: crea el escenario completo de una disputa en la base
    # (sedes, producto, inventario, traslado EN_TRANSITO y su auditoría).
    # =========================================================================
    def _seed(self, status, novelty_type, dispatched, received):
        loc_origin = Location(name="Sede Origen", state="Caracas")
        loc_dest = Location(name="Sede Destino", state="Caracas")
        product = Product(name="Tomate", sku=f"TOM-{status}")
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Admin Test", email=f"admin-{status}@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add_all([loc_origin, loc_dest, product, user])
        db.session.flush()

        inv_origin = Inventory(
            location_id=loc_origin.id, product_id=product.id,
            current_quantity=0, transit_quantity=0, min_stock=20
        )
        db.session.add(inv_origin)
        db.session.flush()

        mov = Movement(
            type="TRASLADO",
            origin_location_id=loc_origin.id,
            destination_location_id=loc_dest.id,
            status=status,
            user_id=user.id
        )
        db.session.add(mov)
        db.session.flush()

        detail = MovementDetail(
            movement_id=mov.id,
            product_id=product.id,
            lot_number="L-001",
            quantity=dispatched,
            received_quantity=received,
            missing_quantity=dispatched - received
        )
        db.session.add(detail)
        db.session.flush()

        # Auditoría de recepción tal como la deja movement_reception_service
        # (esto es lo que le sirve de "memoria" a la bandeja de arbitraje).
        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_NOVEDAD",
            severity="ALERTA",
            user_id=user.id,
            location_id=loc_dest.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RECEPCION_NOVEDAD",
                "notes": "Carga registrada en muelle",
                "erroneous_products_delivered": [],
                "discrepancies": [{
                    "product_id": product.id,
                    "type": novelty_type,
                    "authorized_qty": float(dispatched),
                    "physical_received_qty": float(received),
                    "extra_units": float(max(0, received - dispatched)),
                    "notes": "Novedad registrada"
                }]
            }
        ))
        db.session.commit()

        return {
            "mov": mov, "detail": detail, "product": product,
            "origin": loc_origin, "dest": loc_dest, "user": user,
            "inv_origin": inv_origin
        }

    # =========================================================================
    # CASO 1: FALTANTE aceptado -> conforme en destino + missing a origen
    # =========================================================================
    def test_faltante_aceptado_acredita_conforme_y_reintegra_missing(self):
        # Envían 10 tomates, llegan 8. La resolución decide "quedárselos".
        env = self._seed(
            status="NOVEDAD_FALTANTE", novelty_type="FALTANTE",
            dispatched=10, received=8
        )

        resolve_dispute(env["mov"].id, {
            f"item_{env['detail'].id}_action": "ACEPTAR_RECEPCION",
            "general_notes": "OK, se queda la mercancía"
        }, user_id=env["user"].id)

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        db.session.refresh(env["inv_origin"])

        # 1) La disputa queda cerrada (COMPLETADO).
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # 2) La sede destino recibe los 8 conformes.
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 8.00)
        # 3) La sede origen recupera los 2 que faltaron.
        self.assertEqual(float(env["inv_origin"].current_quantity), 2.00)
        # 4) No debe crearse ningún traslado de retorno.
        self.assertEqual(
            Movement.query.filter_by(return_of_dispute_id=env["mov"].id).count(), 0
        )
        # 5) Queda registrada la auditoría de resolución, apuntando a este traslado.
        resolution = AuditLog.query.filter_by(action="RESOLUCION_DISPUTA").first()
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.changed_data["movement_id"], env["mov"].id)

    # =========================================================================
    # CASO 2: RECHAZO POR ESPACIO -> se devuelve TODO, no se acredita destino
    # =========================================================================
    def test_rechazo_por_espacio_devuelve_todo_sin_acreditar_destino(self):
        # Envían 10 y llegan 10, pero la carga NO cupo y se rechaza.
        env = self._seed(
            status="RECHAZO_POR_ESPACIO", novelty_type="RECHAZO_POR_ESPACIO",
            dispatched=10, received=10
        )

        resolve_dispute(env["mov"].id, {
            f"item_{env['detail'].id}_action": "RETORNO_EMERGENCIA",
            "general_notes": "No cupo la carga en el local"
        }, user_id=env["user"].id)

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()

        returns = Movement.query.filter_by(
            return_of_dispute_id=env["mov"].id
        ).all()

        # 1) La disputa queda cerrada.
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # 2) NADA se acreditó en destino (no se queda mercancía rechazada).
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 0.00)
        # 3) Se creó el traslado de retorno hacia el origen...
        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].status, "EN_TRANSITO")
        # 4) ... con la cantidad completa (10), en el detalle correcto.
        self.assertEqual(len(returns[0].details), 1)
        self.assertEqual(float(returns[0].details[0].quantity), 10.00)


if __name__ == "__main__":
    unittest.main()