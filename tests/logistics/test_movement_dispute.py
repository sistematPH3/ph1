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
from decimal import Decimal

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


# =========================================================================
    # AYUDA: escenario multi-lote (150 tomates = 100 lote A + 50 lote B)
    # =========================================================================
    def _seed_multi_lot(self, status, novelty_type):
        loc_origin = Location(name="Sede Origen", state="Caracas")
        loc_dest = Location(name="Sede Destino", state="Caracas")
        product = Product(name="Tomate", sku="TOM-MULTI")
        role = Role(name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Admin Test", email="admin-multi@test.com",
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

        # Lote A: 100 despachadas, llegaron 30 (faltan 70).
        d_a = MovementDetail(movement_id=mov.id, product_id=product.id, lot_number="LOTE-A",
                             quantity=100, received_quantity=30, missing_quantity=70)
        # Lote B: 50 despachadas, llegaron 50 (completo).
        d_b = MovementDetail(movement_id=mov.id, product_id=product.id, lot_number="LOTE-B",
                             quantity=50, received_quantity=50, missing_quantity=0)
        db.session.add_all([d_a, d_b])
        db.session.flush()

        db.session.add(AuditLog(
            affected_table="movements",
            action="RECEPCION_NOVEDAD",
            severity="ALERTA",
            user_id=user.id,
            location_id=loc_dest.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RECEPCION_NOVEDAD",
                "novelty_type": novelty_type,
                "notes": "Llegaron 80 de 150",
                "erroneous_products_delivered": [],
                "discrepancies": [
                    {"product_id": product.id, "type": "FALTANTE", "authorized_qty": 100.0,
                     "physical_received_qty": 30.0, "extra_units": 0.0, "notes": "Faltan 70 lote A"},
                    {"product_id": product.id, "type": "FALTANTE", "authorized_qty": 50.0,
                     "physical_received_qty": 50.0, "extra_units": 0.0, "notes": "Lote B completo"}
                ]
            }
        ))
        db.session.commit()

        return {"mov": mov, "d_a": d_a, "d_b": d_b, "product": product,
                "origin": loc_origin, "dest": loc_dest, "user": user, "inv_origin": inv_origin}

    # =========================================================================
    # CASO 3: BAJA POR EXTRAVÍO PARCIAL -> no suma a destino ni al origen;
    # la cantidad perdida queda registrada en la auditoría con su lote.
    # =========================================================================
    def test_baja_extraviado_no_acredita_destino_ni_reintegra_origen(self):
        # Envían 10 tomates y llegan 8: los 2 faltantes se declaran perdidos.
        env = self._seed(
            status="NOVEDAD_FALTANTE", novelty_type="FALTANTE",
            dispatched=10, received=8
        )

        resolve_dispute(env["mov"].id, {
            f"item_{env['detail'].id}_action": "BAJA_EXTRAVIO_PARCIAL",
            "general_notes": "Pérdida en ruta, se da de baja el faltante"
        }, user_id=env["user"].id)

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        db.session.refresh(env["inv_origin"])

        # 1) La disputa queda cerrada.
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # 2) Destino recibe SOLO los 8 conformes.
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 8.00)
        # 3) El faltante NO vuelve al origen (se perdió en ruta).
        self.assertEqual(float(env["inv_origin"].current_quantity), 0.00)
        # 4) No se crea traslado de retorno.
        self.assertEqual(
            Movement.query.filter_by(return_of_dispute_id=env["mov"].id).count(), 0
        )
        # 5) La auditoría guarda exactamente cuánto y de qué lote se perdió.
        resolution = AuditLog.query.filter_by(action="RESOLUCION_DISPUTA").first()
        self.assertIsNotNone(resolution)
        item = resolution.changed_data["items"][0]
        self.assertEqual(item["lot_number"], "L-001")
        self.assertEqual(item["lost_qty"], 2.0)
        self.assertEqual(resolution.changed_data["resolution_summary"]["lost_total"], 2.0)

    # =========================================================================
    # CASO 4: MULTI-LOTE -> envío de 150 (100 lote A + 50 lote B), se pierden
    # 70 del lote A: la auditoría debe registrar el lote y la cantidad exacta.
    # =========================================================================
    def test_extraviado_multilote_registra_lote_y_cantidad_correcta(self):
        env = self._seed_multi_lot(status="NOVEDAD_FALTANTE", novelty_type="FALTANTE")

        resolve_dispute(env["mov"].id, {
            f"item_{env['d_a'].id}_action": "BAJA_EXTRAVIO_PARCIAL",
            f"item_{env['d_b'].id}_action": "BAJA_EXTRAVIO_PARCIAL",
            "general_notes": "Se perdieron 70 del lote A en ruta"
        }, user_id=env["user"].id)

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        db.session.refresh(env["inv_origin"])

        # 1) Destino recibe lo que realmente llegó: 30 (lote A) + 50 (lote B) = 80.
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 80.00)
        # 2) Los 70 perdidos NO vuelven al origen.
        self.assertEqual(float(env["inv_origin"].current_quantity), 0.00)
        # 3) La auditoría registra el extravío POR LOTE.
        resolution = AuditLog.query.filter_by(action="RESOLUCION_DISPUTA").first()
        self.assertIsNotNone(resolution)
        items = {i["lot_number"]: i for i in resolution.changed_data["items"]}
        self.assertEqual(items["LOTE-A"]["lost_qty"], 70.0)
        self.assertEqual(items["LOTE-B"]["lost_qty"], 0.0)
        self.assertEqual(resolution.changed_data["resolution_summary"]["lost_total"], 70.0)


# =========================================================================
    # CASO 5: SOBRANTE DEVUELTO -> el origen debita el excedente físico, el
    # destino queda con lo conforme y se crea un retorno con el excedente.
    # =========================================================================
    def test_sobrante_devuelto_debita_excedente_del_origen(self):
        # Envían 10, llegan 12 (2 de sobrante/excedente). El admin decide devolverlos.
        env = self._seed(
            status="SOBRANTE_EXCEDENTE", novelty_type="SOBRANTE_EXCEDENTE",
            dispatched=10, received=12
        )
        # El origen arranca con 10 (ya despachó 10 de 20) y debe perder además los
        # 2 excedentes que físicamente salieron aunque la guía no los reflejara.
        env["inv_origin"].current_quantity = Decimal("10.00")
        # En un sobrante no hay faltante: el muelle nunca registra missing negativo.
        env["detail"].missing_quantity = Decimal("0.00")
        db.session.commit()

        resolve_dispute(env["mov"].id, {
            f"item_{env['detail'].id}_action": "RETORNO_EMERGENCIA",
            "general_notes": "Se devuelve el excedente"
        }, user_id=env["user"].id)

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        db.session.refresh(env["inv_origin"])

        returns = Movement.query.filter_by(return_of_dispute_id=env["mov"].id).all()

        # 1) La disputa queda cerrada.
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # 2) El destino queda con lo conforme (10).
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 10.00)
        # 3) El origen pasa de 10 a 8: debita el excedente (2) que regresa vía retorno.
        self.assertEqual(float(env["inv_origin"].current_quantity), 8.00)
        # 4) Se crea el traslado de retorno con el excedente (2).
        self.assertEqual(len(returns), 1)
        self.assertEqual(float(returns[0].details[0].quantity), 2.00)


if __name__ == "__main__":
    unittest.main()