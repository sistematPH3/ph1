# =============================================================================
# PRUEBA AUTOMÁTICA DEL SERVICIO DE RECEPCIÓN DE TRASLADOS
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Recepción CONFORME: asienta stock en destino y libera el tránsito del origen.
#   2) FALTANTE: NO acredita destino, deja el movimiento en disputa (novedad).
#   3) SOBRANTE: igual que faltante, la diferencia queda para el arbitraje.
#   4) PRODUCTO ERRÓNEO: registra la auditoría de insumos fuera de guía.
#   5) Errores de validación: cantidad ausente, producto erróneo sin insumo,
#      lote no coincide sin lote, faltante sin justificación.
#   6) Permisos: un rol no-admin no puede recibir una sede ajena.
#
# Uso (en la carpeta ph1, Linux/Ubuntu):
#   .venv/bin/python -m unittest tests.logistics.test_movement_reception -v
# =============================================================================

import os
import unittest
from datetime import date

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

from app import create_app, db
from app.models import (
    AuditLog, Inventory, Location, Movement, MovementDetail,
    Product, Purchase, PurchaseDetail, Role, Supplier, User,
)
from app.logistics.services.movement_reception_service import MovementReceptionService


class MovementReceptionTest(unittest.TestCase):

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

    def _seed(self, dispatched=10, role_id=1, user_location_ids=None, transit_from_dispatch=True, origin_current=0.0):
        """Crea el escenario base de una recepción con un movimiento EN_TRANSITO."""
        loc_origin = Location(name="Sede Origen", state="Caracas")
        loc_dest = Location(name="Sede Destino", state="Caracas")
        product = Product(name="Tomate", sku="TOM-REC", unit_of_measure="kg")
        role = Role(name="Rol")
        db.session.add(role)
        db.session.flush()
        user = User(name="Receptor", email="receptor@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add_all([loc_origin, loc_dest, product, user])
        db.session.flush()

        inv_origin = Inventory(
            location_id=loc_origin.id, product_id=product.id,
            current_quantity=origin_current,
            transit_quantity=dispatched if transit_from_dispatch else 0.0,
            min_stock=20
        )
        db.session.add(inv_origin)
        db.session.flush()

        mov = Movement(
            type="TRASLADO",
            origin_location_id=loc_origin.id,
            destination_location_id=loc_dest.id,
            status="EN_TRANSITO",
            user_id=user.id
        )
        db.session.add(mov)
        db.session.flush()

        detail = MovementDetail(
            movement_id=mov.id,
            product_id=product.id,
            lot_number="L-001",
            quantity=dispatched,
            received_quantity=None,
            missing_quantity=0.00
        )
        db.session.add(detail)
        db.session.commit()

        return {
            "mov": mov, "detail": detail, "product": product,
            "origin": loc_origin, "dest": loc_dest, "user": user,
            "user_id": user.id,
            "user_location_ids": user_location_ids if user_location_ids is not None else [loc_dest.id]
        }

    def _process(self, env, novelty_type="CONFORME", notes="", items_override=None,
                 erroneous=None, user_role_id=1, user_location_ids=None):
        detail = env["detail"]
        items = items_override if items_override is not None else [{
            "detail_id": detail.id,
            "received_quantity": float(detail.quantity),
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        payload = {
            "novelty_type": novelty_type,
            "notes": notes,
            "items": items,
            "erroneous_products": erroneous or []
        }
        return MovementReceptionService.process_reception(
            movement_id=env["mov"].id,
            user_id=env["user_id"],
            user_role_id=user_role_id,
            user_location_ids=user_location_ids if user_location_ids is not None else env["user_location_ids"],
            payload=payload
        )

    def _seed_two_items(self, dispatched_a=10, dispatched_b=10):
        """Escenario con dos renglones de guía (para incidencias multi-renglón)."""
        env = self._seed(dispatched=dispatched_a)
        product_b = Product(name="Cilantro", sku="CIL-REC", unit_of_measure="kg")
        db.session.add(product_b)
        db.session.flush()
        detail_b = MovementDetail(
            movement_id=env["mov"].id,
            product_id=product_b.id,
            lot_number="L-002",
            quantity=dispatched_b,
            received_quantity=None,
            missing_quantity=0.00
        )
        db.session.add(detail_b)
        db.session.commit()
        env["detail_b"] = detail_b
        env["product_b"] = product_b
        return env

    # =========================================================================
    # CASO 1: RECEPCIÓN CONFORME -> asienta stock en destino
    # =========================================================================
    def test_recepcion_conforme_asienta_stock(self):
        env = self._seed(dispatched=10)

        ok, msg = self._process(env, novelty_type="CONFORME", notes="")

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        inv_origin = Inventory.query.filter_by(
            location_id=env["origin"].id, product_id=env["product"].id
        ).first()

        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertIsNotNone(inv_dest)
        self.assertEqual(float(inv_dest.current_quantity), 10.00)
        # El tránsito del origen queda liberado (se movió a destino).
        self.assertEqual(float(inv_origin.transit_quantity), 0.00)
        # Se registra una auditoría CONFORME.
        log = AuditLog.query.filter_by(action="RECEPCION_CONFORME").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changed_data["discrepancies"][0]["notes"], "CONFORME")

    # =========================================================================
    # CASO 2: FALTANTE -> NO asienta destino, queda en disputa
    # =========================================================================
    def test_recepcion_faltante_no_acredita_destino(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 8.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="Faltaron 2 tomates", items_override=items)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])

        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()

        # El movimiento queda en novedad (disputa), NO COMPLETADO.
        self.assertEqual(env["mov"].status, "FALTANTE_CONTEO")
        # Nada acreditado en destino todavía.
        if inv_dest is not None:
            self.assertEqual(float(inv_dest.current_quantity), 0.00)
        # La observación del muelle queda registrada en la auditoría.
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changed_data["discrepancies"][0]["notes"], "FALTANTE")

    # =========================================================================
    # CASO 3: SOBRANTE -> no acredita el excedente, queda en disputa
    # =========================================================================
    def test_recepcion_sobrante_no_acredita_excedente(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 12.0,
            "item_condition": "SOBRANTE_EXCEDENTE",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="Llegaron 2 kilos de mas", items_override=items)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "SOBRANTE_EXCEDENTE")

        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changed_data["discrepancies"][0]["notes"], "SOBRANTE")

    # =========================================================================
    # CASO 4: PRODUCTO ERRÓNEO -> registra insumo fuera de guía
    # =========================================================================
    def test_recepcion_producto_erroneo_registra_fuera_de_guia(self):
        env = self._seed(dispatched=10)

        # Un producto que NO viene en la guía y llega por error.
        extra_product = Product(name="Cebolla", sku="CEB-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()

        # El insumo solicitado no llegó físicamente -> 0 recibido (faltante).
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 0.0,
            "item_condition": "FALTANTE_CONTEO",
            "observed_physical_lot": None
        }]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 3.0
        }]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="Llego producto que no era", items_override=items, erroneous=erroneous)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        # REGLA (decisión de diseño): MIXTA exige 2+ renglones afectados.
        # Un único renglón faltante + erróneos => PRODUCTO_ERRONEO (la diferencia
        # del renglón queda registrada en la auditoría para el arbitraje).
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")

        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 1)
        self.assertEqual(
            log.changed_data["erroneous_products_delivered"][0]["quantity_delivered"],
            3.0
        )

    # =========================================================================
    # CASO 4a2: FALTANTE en UN solo renglón + erróneos declarados -> PRODUCTO_ERRONEO
    # (regresión: antes los erróneos se descartaban en silencio si la novedad
    #  general no era PRODUCTO_ERRONEO/INCIDENCIA_MIXTA/CONFORME).
    # (regla 2026: INCIDENCIA_MIXTA exige 2+ renglones afectados; un único
    #  renglón + erróneos queda en PRODUCTO_ERRONEO).
    # =========================================================================
    def test_un_erroneo_con_una_fila_afectada_queda_en_producto_erroneo(self):
        env = self._seed(dispatched=10)

        extra_product = Product(name="Pimenton", sku="PIM-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 0.0,
            "item_condition": "FALTANTE_CONTEO",
            "observed_physical_lot": None
        }]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 2.0,
            "lot_number": "LOT-MIX-1",
            "expiration_date": "2027-01-01"
        }]
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="Faltaron todos", items_override=items, erroneous=erroneous)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        # Un solo renglón afectado + erróneos => PRODUCTO_ERRONEO (la diferencia del
        # renglón igual se registra en la auditoría para el arbitraje).
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")

        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 1)
        self.assertEqual(
            log.changed_data["erroneous_products_delivered"][0]["lot_number"],
            "LOT-MIX-1"
        )

    # =========================================================================
    # CASO 4b: NO se puede declarar como erróneo un producto que SÍ viene en la guía
    # =========================================================================
    def test_no_se_puede_declarar_erroneo_un_producto_de_la_guia(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 0.0,
            "item_condition": "FALTANTE_CONTEO",
            "observed_physical_lot": None
        }]
        # Se intenta declarar como erróneo el MISMO tomate que está en la guía.
        erroneous = [{
            "product_id": env["product"].id,
            "quantity": 3.0
        }]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego tomate", items_override=items, erroneous=erroneous)

        self.assertFalse(ok)
        self.assertTrue(any("ya viene en la guía" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 4c: Si se declara un erróneo válido pero la novedad quedó en CONFORME,
    # el sistema lo fuerza a PRODUCTO_ERRONEO.
    # =========================================================================
    def test_erroneo_declarado_con_novedad_conforme_se_fuerza_a_erroneo(self):
        env = self._seed(dispatched=10)

        extra_product = Product(name="Papa", sku="PAP-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        # La novedad general queda CONFORME pero se declara un insumo no solicitado.
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 2.0
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="llego papa extra", items_override=items, erroneous=erroneous)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")

    # =========================================================================
    # CASO 4d: condición de renglón PRODUCTO_ERRONEO ya no es válida
    # =========================================================================
    def test_condicion_renglon_producto_erroneo_invalida(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 0.0,
            "item_condition": "PRODUCTO_ERRONEO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego mal", items_override=items)

        self.assertFalse(ok)
        self.assertTrue(any("condición" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 4e: insumo erróneo con lote físico y vencimiento autocompletado
    # =========================================================================
    def test_erroneo_registra_lote_y_vencimiento(self):
        env = self._seed(dispatched=10)

        extra_product = Product(name="Cebolla", sku="CEB-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None,
            "observed_physical_expiration": None
        }]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 3.0,
            "lot_number": "LOT-ERR-001",
            "expiration_date": "2027-06-15"
        }]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego cebolla de mas",
                                items_override=items, erroneous=erroneous)

        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")

        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        err = log.changed_data["erroneous_products_delivered"][0]
        self.assertEqual(err["lot_number"], "LOT-ERR-001")
        self.assertEqual(err["expiration_date"], "2027-06-15")

    # =========================================================================
    # CASO 5: ERRORES DE VALIDACIÓN
    # =========================================================================
    def test_falta_cantidad_recibida_da_error_claro(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            # received_quantity NO se envía
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)

        self.assertFalse(ok)
        self.assertTrue(any("cantidad recibida" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_producto_erroneo_sin_insumo_declarado_falla(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 0.0,
            "item_condition": "PRODUCTO_ERRONEO",
            "observed_physical_lot": None
        }]
        # Sin erroneous_products y sin INCIDENCIA_MIXTA -> debe fallar.
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="sin insumo", items_override=items, erroneous=[])

        self.assertFalse(ok)
        self.assertTrue(any("insumo físico" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_lote_no_coincide_sin_lote_falla(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "LOTE_NO_COINCIDE",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="LOTE_NO_COINCIDE", notes="cambio de lote", items_override=items)

        self.assertFalse(ok)
        self.assertTrue(any("lote" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_vencimiento_observado_invalido_da_error(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "LOTE_NO_COINCIDE",
            "observed_physical_lot": "L-999",
            "observed_physical_expiration": "2027-13-40"
        }]
        ok, msg = self._process(env, novelty_type="LOTE_NO_COINCIDE", notes="cambio de lote", items_override=items)

        self.assertFalse(ok)
        self.assertTrue(any("vencimiento" in str(e).lower() or "aaaa-mm-dd" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_con_vencimiento_invalido_da_error(self):
        env = self._seed(dispatched=10)

        extra_product = Product(name="Pepinillo", sku="PEP-BAD", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 1.0,
            "lot_number": "LOT-BAD",
            "expiration_date": "2027-02-30"
        }]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego pepinillo",
                                items_override=items, erroneous=erroneous)

        self.assertFalse(ok)
        self.assertTrue(any("vencimiento" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_faltante_sin_justificacion_falla(self):
        env = self._seed(dispatched=10)

        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 8.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        # Sin notas de muelle (menos de 5 caracteres).
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="no", items_override=items)

        self.assertFalse(ok)
        self.assertTrue(any("justificación" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 5b: DETECCIÓN DE SERIAL (lote físico) EN LA BD
    # El muelle debe saber de inmediato si el serial que escribe ya existe.
    # =========================================================================
    def test_serial_existente_se_detecta(self):
        env = self._seed(dispatched=10)
        # El detail de la guía usa el lote L-001 -> ese serial ya existe en la BD.
        result = MovementReceptionService.get_lot_expiration(env["product"].id, "L-001")
        self.assertTrue(result["exists"])
        self.assertIsNone(result["expiration_date"])

    def test_serial_inexistente_avisa(self):
        env = self._seed(dispatched=10)
        result = MovementReceptionService.get_lot_expiration(env["product"].id, "NO-EXISTE-999")
        self.assertFalse(result["exists"])
        self.assertIsNone(result["expiration_date"])

    # =========================================================================
    # CASO 6: PERMISOS -> rol no-admin no recibe sede ajena
    # =========================================================================
    def test_rol_no_admin_no_recibe_sede_ajena(self):
        env = self._seed(dispatched=10)

        # Rol no-admin (2) con sede distinta a la destino.
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                user_role_id=2, user_location_ids=[999999])

        self.assertFalse(ok)
        self.assertTrue("denegada" in msg.lower() or "permisos" in msg.lower())

    # =========================================================================
    # CASO 7: NOVEDADES DE CALIDAD / CUSTODIA -> severidad INCIDENCIA_CALIDAD
    # =========================================================================
    def test_incidencia_temperatura_registra_calidad(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "INCIDENCIA_TEMPERATURA",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="INCIDENCIA_TEMPERATURA", notes="Temperatura 12 grados en muelle", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "INCIDENCIA_TEMPERATURA")
        log = AuditLog.query.filter_by(action="RECEPCION_INCIDENCIA_CALIDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, "ALERTA")

    def test_violacion_custodia_registra_calidad(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "VIOLACION_CUSTODIA",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="VIOLACION_CUSTODIA", notes="Precinto roto al llegar", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "VIOLACION_CUSTODIA")
        log = AuditLog.query.filter_by(action="RECEPCION_INCIDENCIA_CALIDAD").first()
        self.assertIsNotNone(log)

    def test_rechazo_por_espacio_registra_novedad(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "RECHAZO_POR_ESPACIO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="RECHAZO_POR_ESPACIO", notes="Sin espacio en camara, rechazo parcial", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "RECHAZO_POR_ESPACIO")
        # Es un rechazo operativo (no calidad): se registra como NOVEDAD, no como INCIDENCIA_CALIDAD.
        log_calidad = AuditLog.query.filter_by(action="RECEPCION_INCIDENCIA_CALIDAD").first()
        self.assertIsNone(log_calidad)
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)

    def test_vencimiento_proximo_con_cantidad_exacta_acredita_como_conforme(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "VENCIMIENTO_PROXIMO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="VENCIMIENTO_PROXIMO", notes="Lote vence en 2 dias", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        # REGLA (decisión de diseño): vencimiento próximo con cantidades exactas
        # ingresa como recepción conforme a bodega: status COMPLETADO, NADA de
        # calidad/arbitraje; la alerta FEFO queda en la auditoría (item condition).
        self.assertEqual(env["mov"].status, "COMPLETADO")
        log_calidad = AuditLog.query.filter_by(action="RECEPCION_INCIDENCIA_CALIDAD").first()
        self.assertIsNone(log_calidad)
        log = AuditLog.query.filter_by(action="RECEPCION_CONFORME").first()
        self.assertIsNotNone(log)
        found = next((it for it in log.changed_data["items"] if it["detail_id"] == env["detail"].id), None)
        self.assertEqual(found["item_condition"], "VENCIMIENTO_PROXIMO")

    # =========================================================================
    # CASO 8: LOTE NO COINCIDE -> registra el lote físico observado
    # =========================================================================
    def test_lote_no_coincide_registra_lote_fisico(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "LOTE_NO_COINCIDE",
            "observed_physical_lot": "LOTE-FISICO-NUEVO",
            "observed_physical_expiration": "2027-12-31"
        }]
        ok, msg = self._process(env, novelty_type="LOTE_NO_COINCIDE", notes="Cambio de lote en empaque", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "LOTE_NO_COINCIDE")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        disc = log.changed_data["discrepancies"][0]
        self.assertEqual(disc["notes"], "LOTE_NO_COINCIDE")
        # El lote físico y su vencimiento también deben quedar en las discrepancias
        # (lo consume la bandeja de arbitraje para mostrar el lote real del muelle).
        self.assertEqual(disc["observed_physical_lot"], "LOTE-FISICO-NUEVO")
        self.assertEqual(disc["observed_physical_expiration"], "2027-12-31")
        found = next((it for it in log.changed_data["items"] if it["detail_id"] == env["detail"].id), None)
        self.assertEqual(found["observed_physical_lot"], "LOTE-FISICO-NUEVO")
        self.assertEqual(found["observed_physical_expiration"], "2027-12-31")

    # =========================================================================
    # CASO 9: SOBRANTE en UN renglón + ERRONEO -> PRODUCTO_ERRONEO
    # (regla 2026: INCIDENCIA_MIXTA exige 2+ renglones afectados)
    # =========================================================================
    def test_un_erroneo_con_una_fila_sobrante_queda_en_producto_erroneo(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Zanahoria", sku="ZAN-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 12.0,
            "item_condition": "SOBRANTE_EXCEDENTE",
            "observed_physical_lot": None
        }]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 2.0,
            "lot_number": "LOT-SOB-1",
            "expiration_date": "2028-01-01"
        }]
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="Llego zanahoria de mas", items_override=items, erroneous=erroneous)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 1)

    def test_erroneo_mas_dos_filas_afectadas_dispara_incidencia_mixta(self):
        # Límite de la regla: erróneos + 2 renglones con incidencia SÍ es MIXTA.
        env = self._seed_two_items()
        extra_product = Product(name="Papa", sku="PAP-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [
            {
                "detail_id": env["detail"].id,
                "received_quantity": 8.0,
                "item_condition": "FALTANTE_CONTEO",
                "observed_physical_lot": None
            },
            {
                "detail_id": env["detail_b"].id,
                "received_quantity": 12.0,
                "item_condition": "SOBRANTE_EXCEDENTE",
                "observed_physical_lot": None
            }
        ]
        erroneous = [{
            "product_id": extra_product.id,
            "quantity": 2.0,
            "lot_number": "LOT-MIX-2"
        }]
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="Falta y sobra y llego papa de mas",
                                items_override=items, erroneous=erroneous)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "INCIDENCIA_MIXTA")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 1)
        self.assertEqual(len(log.changed_data["discrepancies"]), 2)

    # =========================================================================
    # CASO 10: EXCEDENTE NO SE ACREDITA EN NOVEDAD (sobrante simple)
    # =========================================================================
    def test_sobrante_no_acredita_excedente_en_stock(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 13.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        # Novedad SOBRANTE declara 13 recibidos, orden era 10.
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="Tres bultos extra", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "SOBRANTE_EXCEDENTE")
        # El stock de destino NO debe llevar el excedente (queda para arbitraje).
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)
        self.assertEqual(inv_dest.transit_quantity, 0.0)

    # =========================================================================
    # CASO 11: ERRORES DE VALIDACIÓN GENERALES
    # =========================================================================
    def test_novedad_invalida_da_error(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="NOVEDAD_INEXISTENTE", notes="x" * 10)
        self.assertFalse(ok)
        self.assertTrue(any("novedad" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_condicion_renglon_invalida_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONDICION_FALSA",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("condición" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_detail_id_ajeno_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": 999999,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("no pertenece" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_cantidad_negativa_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": -5.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("negativ" in str(e).lower() or "cantidad" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_cantidad_no_numerica_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": "abc",
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("inválida" in str(e).lower() or "cantidad" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))


    # =========================================================================
    # CASO 12: VÁRIOS LOTES DEL MISMO PRODUCTO ERRÓNEO
    # =========================================================================
    def test_mismo_producto_erroneo_con_dos_lotes_diferentes(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Tomate", sku="TOM-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [
            {"product_id": extra_product.id, "quantity": 100.0, "lot_number": "LOTE-A", "expiration_date": "2027-01-01"},
            {"product_id": extra_product.id, "quantity": 50.0, "lot_number": "LOTE-B", "expiration_date": "2027-06-01"}
        ]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="Tomate de dos lotes distintos", items_override=items, erroneous=erroneous)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 2)

    def test_mismo_producto_con_mismo_lote_duplica_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Cebolla", sku="CEB-DUP", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [
            {"product_id": extra_product.id, "quantity": 100.0, "lot_number": "LOTE-X", "expiration_date": "2027-01-01"},
            {"product_id": extra_product.id, "quantity": 50.0, "lot_number": "LOTE-X", "expiration_date": "2027-01-01"}
        ]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="Mismo lote duplicado", items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("mismo lote" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 13: FORMAS DEL PAQUETE DE RECEPCIÓN (robustez de validación)
    # =========================================================================
    def test_payload_no_dict_da_error(self):
        env = self._seed(dispatched=10)
        ok, msg = MovementReceptionService.process_reception(
            movement_id=env["mov"].id,
            user_id=env["user_id"],
            user_role_id=1,
            user_location_ids=env["user_location_ids"],
            payload="no soy dict"
        )
        self.assertFalse(ok)
        self.assertTrue(any("formato" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_items_vacios_o_sin_lista_da_error(self):
        env = self._seed(dispatched=10)
        for bad in (None, [], "items"):
            payload = {
                "novelty_type": "CONFORME",
                "notes": "",
                "items": bad,
                "erroneous_products": []
            }
            ok, msg = MovementReceptionService.process_reception(
                movement_id=env["mov"].id,
                user_id=env["user_id"],
                user_role_id=1,
                user_location_ids=env["user_location_ids"],
                payload=payload
            )
            self.assertFalse(ok)
            self.assertTrue(any("no puede estar vacía" in str(e).lower() or "lista" in str(e).lower()
                                for e in (msg if isinstance(msg, list) else [msg])))

    def test_received_quantity_string_vacio_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": "",
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("cantidad" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_recibido_mayor_que_despachado_con_novedad_conforme_genera_sobrante(self):
        # Si el muelle reporta más de lo autorizado pero la novedad quedó CONFORME,
        # el servidor debe derivar SOBRANTE_EXCEDENTE (no NOVEDAD_FALTANTE): un
        # EXCESO no puede etiquetarse como faltante.
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 12.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="Llegaron 2 de mas", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "SOBRANTE_EXCEDENTE")

    def test_lote_no_coincide_solo_espacios_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "LOTE_NO_COINCIDE",
            "observed_physical_lot": "   ",
            "observed_physical_expiration": None
        }]
        ok, msg = self._process(env, novelty_type="LOTE_NO_COINCIDE", notes="cambio de lote", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("lote" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_como_objeto_unico_se_normaliza(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Auyama", sku="AUY-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        # El muelle a veces envía un dict en vez de una lista.
        erroneous = {"product_id": extra_product.id, "quantity": 4.0}
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego auyama",
                                items_override=items, erroneous=erroneous)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertEqual(len(log.changed_data["erroneous_products_delivered"]), 1)

    def test_erroneo_con_id_invalido_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        for bad_id in (0, -1, "abc"):
            erroneous = [{"product_id": bad_id, "quantity": 2.0}]
            ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego algo",
                                    items_override=items, erroneous=erroneous)
            self.assertFalse(ok)
            self.assertTrue(any("producto válido" in str(e).lower()
                                for e in (msg if isinstance(msg, list) else [msg])),
                            f"id {bad_id}: {msg}")

    def test_erroneo_cantidad_cero_da_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Cambur", sku="CAM-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [{"product_id": extra_product.id, "quantity": 0.0}]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego cambur",
                                items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("mayor a cero" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_duplicado_case_insensitive_da_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Lechuga", sku="LEC-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [
            {"product_id": extra_product.id, "quantity": 2.0, "lot_number": "LOTE-Y", "expiration_date": "2027-01-01"},
            {"product_id": extra_product.id, "quantity": 3.0, "lot_number": " lote-y ", "expiration_date": "2027-01-01"}
        ]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="doble lechuga",
                                items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("mismo lote" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_duplicado_sin_lote_da_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Remolacha", sku="REM-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [
            {"product_id": extra_product.id, "quantity": 2.0},
            {"product_id": extra_product.id, "quantity": 3.0}
        ]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="remolacha duplicada",
                                items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("mismo lote" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_sin_justificacion_da_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Pimenton", sku="PIM-EXT2", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [{"product_id": extra_product.id, "quantity": 2.0}]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="sin",
                                items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("justificación" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_incidencia_mixta_multiples_renglones_sin_erroneos(self):
        env = self._seed_two_items()
        items = [
            {
                "detail_id": env["detail"].id,
                "received_quantity": 8.0,
                "item_condition": "FALTANTE_CONTEO",
                "observed_physical_lot": None
            },
            {
                "detail_id": env["detail_b"].id,
                "received_quantity": 12.0,
                "item_condition": "SOBRANTE_EXCEDENTE",
                "observed_physical_lot": None
            }
        ]
        ok, msg = self._process(env, novelty_type="INCIDENCIA_MIXTA", notes="Un insumo falta y otro sobra",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "INCIDENCIA_MIXTA")

    def test_incidencia_mixta_sin_notas_da_error(self):
        env = self._seed_two_items()
        items = [
            {"detail_id": env["detail"].id, "received_quantity": 8.0, "item_condition": "FALTANTE_CONTEO", "observed_physical_lot": None},
            {"detail_id": env["detail_b"].id, "received_quantity": 12.0, "item_condition": "SOBRANTE_EXCEDENTE", "observed_physical_lot": None}
        ]
        ok, msg = self._process(env, novelty_type="INCIDENCIA_MIXTA", notes="no", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("justificación" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 13b: COHERENCIA -> la clasificación general debe tener respaldo en renglones
    # =========================================================================
    def test_clasificacion_faltante_sin_respaldo_da_error(self):
        # Guard anti falso reporte: FALTANTE declarado con TODOS los renglones
        # CONFORME y cantidades exactas => no hay nada que respalde la clasificación.
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="me dijeron que falta", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("no coincide" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "EN_TRANSITO")

    def test_clasificacion_mixta_sin_renglones_afectados_da_error(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="INCIDENCIA_MIXTA", notes="sin respaldo", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("no coincide" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_clasificacion_sobrante_con_respaldo_si_pasa(self):
        # Con la diferencia registrada en el renglón, la clasificación es coherente.
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="llego de mas el tomate", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 12.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "SOBRANTE_EXCEDENTE")

    # =========================================================================
    # CASO 13c: COHERENCIA TIPO-ESPECÍFICA -> la clasificación debe COINCIDIR
    # con la NATURALEZA de las discrepancias (no solo tener algún respaldo)
    # =========================================================================
    def test_clasificacion_sobrante_con_solo_faltantes_da_error(self):
        # SOBRANTE declarado pero los renglones solo evidencian un faltante: la
        # coherencia de signo debe rechazarlo (un exceso no es "falta y sobra").
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="revisar la carga", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 8.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("sobrante" in str(e).lower() or "no coincide" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "EN_TRANSITO")

    def test_clasificacion_temperatura_sin_condicion_da_error(self):
        # Novedad de calidad TEMPERATURA pero ningún renglón llevó la condición:
        # debe rechazarse (la coherencia ya no se conforma con cualquier respaldo).
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="INCIDENCIA_TEMPERATURA", notes="carga templada en muelle", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("temperatura" in str(e).lower() or "no coincide" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_clasificacion_mixta_con_un_solo_renglon_afectado_da_error(self):
        # INCIDENCIA_MIXTA exige DOS o más renglones afectados (regla de diseño):
        # con un solo renglón la coherencia debe rechazarla.
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="INCIDENCIA_MIXTA", notes="una sola fila afectada", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 8.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("mixta" in str(e).lower() or "no coincide" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 14: CONTRATOS DEL SERVICIO (estados, permisos, auditoría)
    # =========================================================================
    def test_movimiento_inexistente_da_error(self):
        env = self._seed(dispatched=10)
        ok, msg = MovementReceptionService.process_reception(
            movement_id=999999,
            user_id=env["user_id"],
            user_role_id=1,
            user_location_ids=env["user_location_ids"],
            payload={}
        )
        self.assertFalse(ok)
        self.assertIn("no encontrado", str(msg).lower())

    def test_movimiento_no_en_transito_da_error(self):
        env = self._seed(dispatched=10)
        env["mov"].status = "COMPLETADO"
        db.session.commit()
        ok, msg = self._process(env, novelty_type="CONFORME", notes="")
        self.assertFalse(ok)
        self.assertTrue("no puede ser recibido" in msg.lower() or "no está en tránsito" in msg.lower())

    def test_admin_recibe_sede_ajena(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                user_role_id=1, user_location_ids=[999999])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")

    def test_recepcion_conforme_no_toca_current_del_origen(self):
        env = self._seed(dispatched=10, origin_current=5.0)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="")
        self.assertTrue(ok, msg)
        inv_origin = Inventory.query.filter_by(
            location_id=env["origin"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(float(inv_origin.current_quantity), 5.00)
        self.assertEqual(float(inv_origin.transit_quantity), 0.00)
        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(float(inv_dest.current_quantity), 10.00)

    def test_sobrante_condicion_sin_diferencia_no_genera_extra(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "SOBRANTE_EXCEDENTE",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE",
                                notes="Condicion sobrante con cantidades iguales", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "SOBRANTE_EXCEDENTE")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        disc = log.changed_data["discrepancies"][0]
        self.assertEqual(disc["extra_units"], 0.0)
        self.assertEqual(disc["type"], "SOBRANTE_EXCEDENTE")

    def test_sobrante_sin_notas_da_error(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 12.0,
            "item_condition": "SOBRANTE_EXCEDENTE",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="SOBRANTE_EXCEDENTE", notes="nope", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("justificación" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_novedad_registra_severidad_alerta(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 8.0,
            "item_condition": "FALTANTE_CONTEO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="Faltaron 2 unidades", items_override=items)
        self.assertTrue(ok, msg)
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertEqual(log.severity, "ALERTA")

    def test_erroneo_producto_inexistente_da_error(self):
        # Un ID que no existe en el catálogo debe rechazarse: si llegara al arbitraje
        # crearía inventario con una FK huérfana.
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        erroneous = [{"product_id": 999999, "quantity": 2.0}]
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego insumo raro",
                                items_override=items, erroneous=erroneous)
        self.assertFalse(ok)
        self.assertTrue(any("no existe" in str(e).lower()
                            for e in (msg if isinstance(msg, list) else [msg])))

    def test_vencimiento_proximo_con_cantidad_exacta_acredita_stock(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 10.0,
            "item_condition": "VENCIMIENTO_PROXIMO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="VENCIMIENTO_PROXIMO", notes="Lote vence proximo", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        # REGLA (decisión de diseño): vencimiento próximo SIN faltante/sobrante
        # acredita el stock en destino como una recepción conforme (alerta FEFO
        # en auditoría) y el movimiento sale en COMPLETADO, no va a arbitraje.
        self.assertEqual(env["mov"].status, "COMPLETADO")
        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(inv_dest.current_quantity, 10.0)
        inv_origin = Inventory.query.filter_by(
            location_id=env["origin"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(inv_origin.transit_quantity, 0.0)

    def test_vencimiento_proximo_con_faltante_si_va_a_disputa(self):
        env = self._seed(dispatched=10)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 8.0,
            "item_condition": "VENCIMIENTO_PROXIMO",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="VENCIMIENTO_PROXIMO", notes="Vence y ademas faltan 2", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        # Si además hay faltante/sobrante REAL, ya no es "acreditar conforme": el
        # movimiento queda VENCIMIENTO_PROXIMO (incidencia) para arbitraje y NO
        # acredita destino todavía.
        self.assertEqual(env["mov"].status, "VENCIMIENTO_PROXIMO")
        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)

    # =========================================================================
    # CASO 14b: CARGA DE DATOS DE LA RECEPCIÓN (view)
    # =========================================================================
    def test_get_reception_data_devuelve_movimiento_y_detalles(self):
        env = self._seed(dispatched=10)
        data, err = MovementReceptionService.get_reception_data(
            env["mov"].id, env["user_location_ids"], 1
        )
        self.assertIsNone(err)
        self.assertEqual(data["movement"]["status"], "EN_TRANSITO")
        self.assertEqual(len(data["details"]), 1)

    def test_get_reception_data_movimiento_inexistente(self):
        data, err = MovementReceptionService.get_reception_data(999999, [1], 1)
        self.assertIsNone(data)
        self.assertIn("no encontrado", err.lower())

    def test_get_reception_data_movimiento_no_en_transito(self):
        env = self._seed(dispatched=10)
        env["mov"].status = "COMPLETADO"
        db.session.commit()
        data, err = MovementReceptionService.get_reception_data(
            env["mov"].id, env["user_location_ids"], 1
        )
        self.assertIsNone(data)
        self.assertTrue("no está en tránsito" in err.lower())

    # =========================================================================
    # CASO 15: RECUPERACIÓN DEL VENCIMIENTO DE UN LOTE (autocompletado del muelle)
    # =========================================================================
    def test_vencimiento_se_recupera_del_movimiento(self):
        env = self._seed(dispatched=10)
        env["detail"].expiration_date = date(2027, 3, 3)
        db.session.commit()
        result = MovementReceptionService.get_lot_expiration(env["product"].id, "L-001")
        self.assertTrue(result["exists"])
        self.assertEqual(result["expiration_date"], "2027-03-03")

    def test_vencimiento_se_recupera_de_las_compras(self):
        env = self._seed(dispatched=10)
        supplier = Supplier(name="Proveedor Test", tax_id="J-90000000-0")
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(
            supplier_id=supplier.id, invoice_url="recibo.pdf",
            total_amount=0.0, currency="VES", exchange_rate=1.0,
            user_id=env["user_id"]
        )
        db.session.add(purchase)
        db.session.flush()
        pd = PurchaseDetail(
            purchase_id=purchase.id, product_id=env["product"].id,
            lot_number="LOTE-COMPRA-1", quantity=50.0,
            expiration_date=date(2027, 5, 1)
        )
        db.session.add(pd)
        db.session.commit()
        result = MovementReceptionService.get_lot_expiration(env["product"].id, "LOTE-COMPRA-1")
        self.assertTrue(result["exists"])
        self.assertEqual(result["expiration_date"], "2027-05-01")

    def test_lote_vacio_no_consulta_la_bd(self):
        env = self._seed(dispatched=10)
        for bad_lot in (None, "", "   "):
            result = MovementReceptionService.get_lot_expiration(env["product"].id, bad_lot)
            self.assertFalse(result["exists"])
            self.assertIsNone(result["expiration_date"])

    # =========================================================================
    # CASO 15c: MATRIZ DE ROBUSTEZ (payloads mal formados NO deben lanzar 500)
    # =========================================================================
    def test_mismo_renglon_de_la_guia_repetido_da_error(self):
        # Protección anti doble-asiento: el MISMO detail_id dos veces en la lista
        # items acreditaría el stock dos veces en destino (bug detectado).
        env = self._seed(dispatched=10)
        items = [
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None},
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("más de una vez" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertIsNone(inv_dest)

    def test_renglon_no_dict_no_rompe_la_validacion(self):
        env = self._seed(dispatched=10)
        items = [
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None},
            "soy_un_string_roto"
        ]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=items)
        self.assertFalse(ok)
        self.assertTrue(any("objeto" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_renglon_sin_identificador_da_error(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=[
            {"received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertFalse(ok)
        self.assertTrue(any("no pertenece" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_renglon_sin_condicion_se_trata_como_conforme(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")

    def test_erroneos_formato_no_lista_no_rompe_la_validacion(self):
        env = self._seed(dispatched=10)
        payload = {
            "novelty_type": "PRODUCTO_ERRONEO",
            "notes": "llego insumo de mas",
            "items": [{"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}],
            "erroneous_products": "no soy una lista"
        }
        ok, msg = MovementReceptionService.process_reception(
            movement_id=env["mov"].id, user_id=env["user_id"], user_role_id=1,
            user_location_ids=env["user_location_ids"], payload=payload
        )
        self.assertFalse(ok)
        self.assertTrue(any("formato no válido" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_elemento_no_dict_no_rompe_la_validacion(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="insumo raro", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ], erroneous=[None, {"product_id": 1, "quantity": 2.0}])
        self.assertFalse(ok)
        self.assertTrue(any("formato inválido" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_notas_none_no_rompe_la_validacion(self):
        env = self._seed(dispatched=10)
        payload = {
            "novelty_type": "FALTANTE_CONTEO",
            "notes": None,
            "items": [{"detail_id": env["detail"].id, "received_quantity": 8.0, "item_condition": "FALTANTE_CONTEO", "observed_physical_lot": None}],
            "erroneous_products": []
        }
        ok, msg = MovementReceptionService.process_reception(
            movement_id=env["mov"].id, user_id=env["user_id"], user_role_id=1,
            user_location_ids=env["user_location_ids"], payload=payload
        )
        # Hay discrepancia, así que notas cortas (vacías) => error limpio, no crash.
        self.assertFalse(ok)
        self.assertTrue(any("justificación" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    def test_erroneo_cantidad_no_numerica_da_error(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Brocoli", sku="BRO-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego brocoli", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ], erroneous=[{"product_id": extra_product.id, "quantity": "abc"}])
        self.assertFalse(ok)
        self.assertTrue(any("no numérico" in str(e).lower() for e in (msg if isinstance(msg, list) else [msg])))

    # =========================================================================
    # CASO 15d: AUDIO 5 -> "0 = no vino, poco = faltó, más = sobró" (conforme auto)
    # =========================================================================
    def test_cantidad_recibida_string_numerico_funciona(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": "10", "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")

    def test_conforme_con_recibido_menor_genera_faltante_automatico(self):
        # "Me llegó menos" con el renglón en CONFORME => el sistema deriva el estatus
        # real FALTANTE_CONTEO (justo lo que el JS auto-etiqueta como "Me faltó").
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="llego menos de la cuenta", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 8, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "FALTANTE_CONTEO")
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)
        inv_orig = Inventory.query.filter_by(location_id=env["origin"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_orig.transit_quantity, 0.0)
        detail = db.session.get(MovementDetail, env["detail"].id)
        self.assertEqual(float(detail.missing_quantity), 2.0)

    def test_cero_recibido_es_faltante_total(self):
        # "0 = no vino" => faltante (conforme autodiagnosticado).
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="no llego nada", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "FALTANTE_CONTEO")
        detail = db.session.get(MovementDetail, env["detail"].id)
        self.assertEqual(float(detail.missing_quantity), 10.0)

    def test_condicion_faltante_con_cantidad_exacta_no_asienta(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="revisar calidad", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10, "item_condition": "FALTANTE_CONTEO", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "FALTANTE_CONTEO")
        detail = db.session.get(MovementDetail, env["detail"].id)
        self.assertEqual(float(detail.missing_quantity), 0.0)
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)

    # =========================================================================
    # CASO 15e: AUDIO 2 y 6 -> combos de VENCIMIENTO (alerta FEFO)
    # =========================================================================
    def test_vencimiento_proximo_mas_sobrante_va_a_disputa(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="VENCIMIENTO_PROXIMO", notes="vence y sobra de mas", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 12, "item_condition": "VENCIMIENTO_PROXIMO", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "VENCIMIENTO_PROXIMO")
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)

    def test_mixta_de_vencimiento_y_faltante_en_dos_renglones(self):
        # Combo típico de Mariuska: un lote por vencer + otro faltante.
        env = self._seed_two_items()
        items = [
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "VENCIMIENTO_PROXIMO", "observed_physical_lot": None},
            {"detail_id": env["detail_b"].id, "received_quantity": 8.0, "item_condition": "FALTANTE_CONTEO", "observed_physical_lot": None}
        ]
        ok, msg = self._process(env, novelty_type="INCIDENCIA_MIXTA", notes="uno vence y el otro falta", items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "INCIDENCIA_MIXTA")
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 0.0)
        # Incluye un lote por vencer => la bitácora se registra como incidencia de
        # calidad (conserva las 2 discrepancias para el arbitraje).
        log = AuditLog.query.filter_by(location_id=env["dest"].id).first()
        self.assertIsNotNone(log)
        self.assertEqual(len(log.changed_data["discrepancies"]), 2)

    def test_vencimiento_general_sin_condicion_en_renglones_acredita(self):
        # El operario elige "Vencimiento Próximo" general pero no marca ningún
        # renglón: cantidades exactas => acredita conforme y deja la alerta en la
        # auditoría (novelty_type). No bloquea stock.
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="VENCIMIENTO_PROXIMO", notes="lote general por vencer", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10, "item_condition": "CONFORME", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        log = AuditLog.query.filter_by(action="RECEPCION_CONFORME").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changed_data["novelty_type"], "VENCIMIENTO_PROXIMO")

    def test_conforme_general_con_condicion_vencimiento_acredita_como_conforme(self):
        # Payload CONFORME + renglón marcado VENCIMIENTO_PROXIMO con cantidad exacta:
        # el estatus se deriva a VENCIMIENTO_PROXIMO y, sin diferencias ni erróneos,
        # acredita igual que una recepción conforme (alerta FEFO). Antes del fix se
        # etiquetaba genéricamente como NOVEDAD_FALTANTE pese a no faltar nada.
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="CONFORME", notes="lote por vencer en entrega", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "VENCIMIENTO_PROXIMO", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        inv_dest = Inventory.query.filter_by(location_id=env["dest"].id, product_id=env["product"].id).first()
        self.assertEqual(inv_dest.current_quantity, 10.0)
        log = AuditLog.query.filter_by(action="RECEPCION_CONFORME").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changed_data["novelty_type"], "CONFORME")
        self.assertEqual(log.changed_data["items"][0]["item_condition"], "VENCIMIENTO_PROXIMO")

    # =========================================================================
    # CASO 15f: AUDITORÍA COMPLETA (detalle de items, discrepancias y contexto)
    # =========================================================================
    def test_audit_completo_contiene_items_discrepancias_y_contexto(self):
        env = self._seed(dispatched=10)
        ok, msg = self._process(env, novelty_type="FALTANTE_CONTEO", notes="llegaron 2 kilos de menos", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 8, "item_condition": "FALTANTE_CONTEO", "observed_physical_lot": None}
        ])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].received_by_id, env["user"].id)
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.severity, "ALERTA")
        data = log.changed_data
        self.assertEqual(data["novelty_type"], "FALTANTE_CONTEO")
        self.assertEqual(data["origin_location_id"], env["origin"].id)
        self.assertEqual(data["destination_location_id"], env["dest"].id)
        self.assertEqual(data["received_by_user_id"], env["user"].id)
        self.assertEqual(data["notes"], "llegaron 2 kilos de menos")
        it = data["items"][0]
        self.assertEqual(it["detail_id"], env["detail"].id)
        self.assertEqual(it["product_id"], env["product"].id)
        self.assertEqual(it["sku"], "TOM-REC")
        self.assertEqual(it["product_name"], "Tomate")
        self.assertEqual(it["lot_number"], "L-001")
        self.assertEqual(it["dispatched_qty"], 10.0)
        self.assertEqual(it["received_qty"], 8.0)
        self.assertEqual(it["missing_qty"], 2.0)
        self.assertEqual(it["item_condition"], "FALTANTE_CONTEO")
        self.assertEqual(it["specific_novelty"], "FALTANTE")
        disc = data["discrepancies"][0]
        self.assertEqual(disc["detail_id"], env["detail"].id)
        self.assertEqual(disc["product_id"], env["product"].id)
        self.assertEqual(disc["lot_number"], "L-001")
        self.assertEqual(disc["type"], "FALTANTE_CONTEO")
        self.assertEqual(disc["authorized_qty"], 10.0)
        self.assertEqual(disc["physical_received_qty"], 8.0)
        self.assertEqual(disc["extra_units"], 0.0)
        # (fix coherencia) la bandeja de arbitraje consume missing_qty: la discrepancia
        # debe llevarlo explícitamente, no depender de derivar detail.missing_quantity.
        self.assertEqual(disc["missing_qty"], 2.0)
        self.assertEqual(disc["notes"], "FALTANTE")

    # =========================================================================
    # CASO 15g: ERRÓNEOS -> variantes de formato id/cantidad/lote/vencimiento
    # =========================================================================
    def test_erroneo_con_product_id_y_cantidad_string_se_normaliza(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Apio", sku="API-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego apio de mas", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ], erroneous=[{"product_id": str(extra_product.id), "quantity": "2.5"}])
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "PRODUCTO_ERRONEO")
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        err = log.changed_data["erroneous_products_delivered"][0]
        self.assertEqual(float(err["quantity_delivered"]), 2.5)

    def test_erroneo_con_vencimiento_sin_lote_se_registra(self):
        env = self._seed(dispatched=10)
        extra_product = Product(name="Vea", sku="VEA-EXT", unit_of_measure="kg")
        db.session.add(extra_product)
        db.session.flush()
        ok, msg = self._process(env, novelty_type="PRODUCTO_ERRONEO", notes="llego vea de mas", items_override=[
            {"detail_id": env["detail"].id, "received_quantity": 10.0, "item_condition": "CONFORME", "observed_physical_lot": None}
        ], erroneous=[{"product_id": extra_product.id, "quantity": 1.0, "expiration_date": "2027-05-05"}])
        self.assertTrue(ok, msg)
        log = AuditLog.query.filter_by(action="RECEPCION_NOVEDAD").first()
        err = log.changed_data["erroneous_products_delivered"][0]
        self.assertEqual(err["expiration_date"], "2027-05-05")
        self.assertIsNone(err["lot_number"])

    def test_lot_expiration_product_id_invalido_no_consulta(self):
        result = MovementReceptionService.get_lot_expiration("no-es-numero", "L-001")
        self.assertFalse(result["exists"])
        self.assertIsNone(result["expiration_date"])

    # =========================================================================
    # CASO 16: RUTAS HTTP -> todas exigen autenticación (redirigen al login)
    # =========================================================================
    def test_ruta_recepcion_requiere_login(self):
        env = self._seed(dispatched=10)
        resp = self.app.test_client().get(
            f"/logistics/movements/reception/{env['mov'].id}", follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))

    def test_ruta_lot_expiration_requiere_login(self):
        resp = self.app.test_client().get(
            "/logistics/movements/reception/lot-expiration", follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))

    def test_ruta_process_requiere_login(self):
        resp = self.app.test_client().post(
            "/logistics/movements/reception/1/process",
            json={"items": []},
            follow_redirects=False
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))

    # =========================================================================
    # CASO 17: E2E POR HTTP -> flujo completo autenticado (navegador simulado)
    # =========================================================================
    def _e2e_login(self, env):
        """Deja al usuario como 'Management' con la sede destino asignada y abre
        un cliente autenticado por sesión flask-login (como tras iniciar sesión)."""
        env["user"].role.name = "Management"
        env["user"].locations.append(env["dest"])
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user"].id)
        return client

    def test_e2e_flujo_completo_por_http(self):
        env = self._seed(dispatched=10)
        client = self._e2e_login(env)

        resp_get = client.get(f"/logistics/movements/reception/{env['mov'].id}")
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn("Recepción Física de Traslado", resp_get.get_data(as_text=True))

        payload = {
            "novelty_type": "CONFORME",
            "notes": "",
            "items": [{
                "detail_id": env["detail"].id,
                "received_quantity": 10.0,
                "item_condition": "CONFORME",
                "observed_physical_lot": None
            }],
            "erroneous_products": []
        }
        resp = client.post(
            f"/logistics/movements/reception/{env['mov'].id}/process",
            json=payload
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["redirect_url"], "/logistics/movements")

        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        inv_dest = Inventory.query.filter_by(
            location_id=env["dest"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(inv_dest.current_quantity, 10.0)
        inv_origin = Inventory.query.filter_by(
            location_id=env["origin"].id, product_id=env["product"].id
        ).first()
        self.assertEqual(inv_origin.transit_quantity, 0.0)

    def test_e2e_rechazo_http_no_cambia_estado(self):
        env = self._seed(dispatched=10)
        client = self._e2e_login(env)

        payload = {
            "novelty_type": "FALTANTE_CONTEO",
            "notes": "",
            "items": [{
                "detail_id": env["detail"].id,
                "received_quantity": 8.0,
                "item_condition": "CONFORME",
                "observed_physical_lot": None
            }],
            "erroneous_products": []
        }
        resp = client.post(
            f"/logistics/movements/reception/{env['mov'].id}/process",
            json=payload
        )
        self.assertEqual(resp.status_code, 422)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertTrue(any("justificación" in str(m).lower()
                            for m in (data["message"] if isinstance(data["message"], list) else [data["message"]])))

        db.session.refresh(env["mov"])
        self.assertEqual(env["mov"].status, "EN_TRANSITO")

    # =========================================================================
    # CASO 14: RECEPCIÓN DE UN RETORNO_EMERGENCIA (mercancía devuelta)
    # La bandeja de arbitraje crea el retorno al resolver una disputa. Al
    # recibirlo en el origen NO debe acreditarse como una recepción genérica:
    #   - Insumos ERRÓNEOS (fuera de guía): nunca se debitaron del origen, por
    #     lo que recibirlos no vuelve a acreditarlos (bug de doble conteo).
    #   - Mercancía de la guía (rechazo/faltante): el origen sí la debitó al
    #     despachar; aquí se repone solo lo pendiente (despachado - conforme).
    # =========================================================================
    def _seed_return(self, ret_qty=200.0, erroneous=True, orig_received=None,
                     origin_current=1200.0, return_transit=200.0, dispute_link=True,
                     lot_number="TOM-LOTE-01"):
        """Escenario de recepción de un RETORNO_EMERGENCIA en la sede origen.

        Simula lo que deja la bandeja de arbitraje tras resolver una disputa:
          - Despacho original Central->Sucursal ya resuelto (COMPLETADO) con su
            renglón de guía (recibido conforme = orig_received).
          - Movimiento de retorno Sucursal->Central EN_TRANSITO, con
            return_of_dispute_id apuntando al despacho (si dispute_link=True)
            y su renglón (ret_qty).
          - El tránsito del retorno queda en la sede que devuelve
            (return_transit). Central parte con origin_current del producto.
        Si erroneous=True, el producto/lote devuelto NUNCA estuvo en la guía
        original (insumo erróneo); en otro caso es el mismo renglón.
        """
        loc_central = Location(name="Central", state="Caracas")
        loc_sucu = Location(name="Sucursal", state="Miranda")
        role = Role(name="Rol")
        db.session.add(role)
        db.session.flush()
        user = User(name="Receptor", email="receptor@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add_all([loc_central, loc_sucu, user])
        db.session.flush()

        guia_prod = Product(name="Tomate", sku="TOM-RET", unit_of_measure="kg")
        db.session.add(guia_prod)
        db.session.flush()

        ret_prod = guia_prod
        guia_lot = lot_number
        ret_lot = guia_lot
        if erroneous:
            ret_prod = Product(name="Queso", sku="QUE-EXT", unit_of_measure="kg")
            db.session.add(ret_prod)
            db.session.flush()
            ret_lot = "QUE-2026-01"

        orig = Movement(
            type="DESPACHO",
            origin_location_id=loc_central.id,
            destination_location_id=loc_sucu.id,
            status="COMPLETADO",
            user_id=user.id
        )
        db.session.add(orig)
        db.session.flush()
        received = orig_received if orig_received is not None else 100.0
        orig_detail = MovementDetail(
            movement_id=orig.id, product_id=guia_prod.id, lot_number=guia_lot,
            quantity=100.0, received_quantity=received,
            missing_quantity=max(0.0, 100.0 - received)
        )
        db.session.add(orig_detail)
        db.session.flush()

        inv_central = Inventory(
            location_id=loc_central.id, product_id=ret_prod.id,
            current_quantity=origin_current, transit_quantity=0, min_stock=20
        )
        inv_sucu = Inventory(
            location_id=loc_sucu.id, product_id=ret_prod.id,
            current_quantity=0, transit_quantity=return_transit, min_stock=20
        )
        db.session.add_all([inv_central, inv_sucu])
        db.session.flush()

        ret = Movement(
            type="RETORNO_EMERGENCIA",
            origin_location_id=loc_sucu.id,
            destination_location_id=loc_central.id,
            status="EN_TRANSITO",
            user_id=user.id,
            return_of_dispute_id=orig.id if dispute_link else None
        )
        db.session.add(ret)
        db.session.flush()
        ret_detail = MovementDetail(
            movement_id=ret.id, product_id=ret_prod.id, lot_number=ret_lot,
            quantity=ret_qty, received_quantity=None, missing_quantity=0.0
        )
        db.session.add(ret_detail)
        db.session.commit()

        return {
            "mov": ret, "detail": ret_detail, "ret_prod": ret_prod, "ret_lot": ret_lot,
            "orig": orig, "orig_detail": orig_detail, "guia_prod": guia_prod,
            "central": loc_central, "sucu": loc_sucu, "user": user,
            "user_id": user.id, "user_location_ids": [loc_central.id],
            "inv_central": inv_central, "inv_sucu": inv_sucu
        }

    def test_retorno_erroneo_no_duplica_stock_en_central(self):
        # Un erróneo (fuera de guía) nunca se debitó del origen: recibir el
        # retorno NO debe acreditarlo otra vez. Regresión: Central subía a 1400.
        env = self._seed_return(erroneous=True, ret_qty=200.0,
                                origin_current=1200.0, return_transit=200.0)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 200.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # Central NO recibe el erróneo de vuelta: su stock queda igual.
        self.assertEqual(float(env["inv_central"].current_quantity), 1200.00)
        # El tránsito de la sede que devolvió queda liberado.
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_por_rechazo_repone_lo_despachado(self):
        # La mercancía SÍ venía en la guía y se rechazó (recibido conforme = 0):
        # al recibir el retorno, Central recupera su salida original.
        env = self._seed_return(erroneous=False, ret_qty=100.0, orig_received=0.0,
                                origin_current=100.0, return_transit=100.0)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 100.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertEqual(float(env["inv_central"].current_quantity), 200.00)
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_faltante_reintegra_solo_el_faltante(self):
        # Despacharon 100, llegaron 80 conformes; el faltante (20) se devuelve:
        # Central solo recupera los 20 pendientes de esa guía.
        env = self._seed_return(erroneous=False, ret_qty=20.0, orig_received=80.0,
                                origin_current=100.0, return_transit=20.0)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 20.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertEqual(float(env["inv_central"].current_quantity), 120.00)
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_nunca_acredita_mas_que_lo_pendiente(self):
        # El retorno trae 30 pero la guía solo dejó pendiente 20: no se acreditan
        # los 30, únicamente el saldo real (sin meter stock que jamás salió).
        env = self._seed_return(erroneous=False, ret_qty=30.0, orig_received=80.0,
                                origin_current=100.0, return_transit=30.0)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 30.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertEqual(float(env["inv_central"].current_quantity), 120.00)
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_sin_disputa_vinculada_no_acredita(self):
        # Retorno sin return_of_dispute_id: no hay despacho que contrastar; por
        # seguridad no se acredita nada (protección contra el doble asiento).
        env = self._seed_return(erroneous=False, ret_qty=50.0, orig_received=100.0,
                                origin_current=200.0, return_transit=50.0,
                                dispute_link=False)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 50.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertEqual(float(env["inv_central"].current_quantity), 200.00)
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_sin_lote_repone_cuando_la_guia_tampoco_tiene_lote(self):
        # Insumo sin lote (S/L) en la guía original y en la devolución: el
        # contraste debe hacerse por producto (lote NULL), no devolver 0. Regresión:
        # el saldo pendiente se perdía y el tránsito se liberaba sin acreditar nada.
        env = self._seed_return(erroneous=False, ret_qty=100.0, orig_received=0.0,
                                origin_current=100.0, return_transit=100.0,
                                lot_number=None)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 100.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        self.assertEqual(float(env["inv_central"].current_quantity), 200.00)
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)

    def test_retorno_sobrante_devuelto_repone_el_excedente_al_central(self):
        # Despacharon 100 en guía, pero llegaron 150 (50 de SOBRANTE). El
        # excedente se devolvió al Central en un RETORNO_EMERGENCIA. El origen
        # debitó ese excedente al resolver la disputa (extra_units), así que al
        # RECIBIR el retorno el Central debe recuperar los 50. Con el flujo viejo
        # get_outstanding_dispatch_debit devolvía 0 para sobrantes y el Central
        # se quedaba corto (no se le sumaba la devolución).
        env = self._seed_return(erroneous=False, ret_qty=50.0, orig_received=150.0,
                                origin_current=100.0, return_transit=50.0)
        items = [{
            "detail_id": env["detail"].id,
            "received_quantity": 50.0,
            "item_condition": "CONFORME",
            "observed_physical_lot": None
        }]
        ok, msg = self._process(env, novelty_type="CONFORME", notes="",
                                items_override=items)
        self.assertTrue(ok, msg)
        db.session.refresh(env["mov"])
        db.session.refresh(env["inv_central"])
        db.session.refresh(env["inv_sucu"])
        self.assertEqual(env["mov"].status, "COMPLETADO")
        # Central recupera los 50 sobrantes devueltos: 100 -> 150.
        self.assertEqual(float(env["inv_central"].current_quantity), 150.00)
        # El tránsito de la sede que devolvió queda liberado.
        self.assertEqual(float(env["inv_sucu"].transit_quantity), 0.00)


if __name__ == "__main__":
    unittest.main()
