# =============================================================================
# PRUEBA AUTOMÁTICA DEL REGISTRO DE MERMA (MÓDULO 7 - register_waste)
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Merma APROBADA: descuenta stock del producto, deja trazabilidad (AuditLog)
#      y reduce la disponibilidad del lote.
#   2) Merma PENDIENTE (tipo sensible o cantidad >= waste_limit):
#      NO descuenta el stock físico, notifica a administradores y deja
#      trazabilidad ALERTA; aunque reduce la disponibilidad (reserva) del
#      lote porque esa cantidad ya está "en proceso".
#   3) Anti doble-cargo: dos líneas del mismo producto o del mismo lote que
#      superan el stock/saldo del lote en UN ticket son rechazadas.
#   4) Validaciones: lote insuficiente, lote inexistente, producto sin inventario,
#      tipo inactivo.
#   5) Permisos: un rol no-admin no puede registrar merma en una sede ajena.
#   6) Sede Central (id=1): los tipos que aplican son los sensibles
#      (TEMPERATURA, ROBO_SOSPECHA) y el registro sigue el flujo normal.
#   7) Validador de payload: items vacíos, lote faltante, cantidad inválida,
#      motivo requerido.
#
# Uso (en la carpeta ph1, Linux/Ubuntu):
#   .venv/bin/python -m unittest tests.logistics.test_register_waste -v
# =============================================================================

import io
import os
import unittest
from datetime import date, datetime, timedelta

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
    AuditLog, AppParameter, Inventory, Location, Movement, MovementDetail, Notification,
    Product, Purchase, PurchaseDetail, Role, Supplier, User, Waste,
    WasteDetail, WasteDetailPhoto, WasteType,
)
from app.waste.services.register_waste_service import get_form_data, register_waste
from app.waste.repositories.register_waste_repository import RegisterWasteRepository


ROLE_IDS = {
    "Administrator": 1,
    "Operations": 2,
    "Manager": 3,
}


class WasteRegisterTest(unittest.TestCase):

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

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _seed_env(self, stock=100.0, waste_limit=None, waste_type=None,
                  user_role="Administrator", lot_expiration=None):
        """Escenario base: sede, producto, lote y usuario.

        La disponibilidad del lote para sedes NO centrales se calcula desde
        MovementDetail (el repositorio reutiliza la derivación de consumo),
        por eso el lote entra como un traslado COMPLETADO al destino.
        Por defecto el lote YA ESTÁ VENCIDO (para el tipo VENCIDO); para un
        lote vigente pasar lot_expiration a una fecha futura.
        """
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=30)
        if waste_type is None:
            waste_type = WasteType(
                name="Vencido", code="VENCIDO",
                severity="MEDIA", requires_approval=False,
                applies_central=False, is_active=True,
            )
        db.session.add(waste_type)
        db.session.flush()

        loc_origin = Location(name="Sede Origen", state="Caracas")
        db.session.add(loc_origin)
        db.session.flush()

        loc = Location(name="Sede Prueba", state="Caracas")
        db.session.add(loc)
        db.session.flush()

        product = Product(
            name="Tomate", sku=f"TOM-{waste_type.id}",
            unit_of_measure="kg",
            waste_limit=waste_limit,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        role = Role(id=ROLE_IDS[user_role], name=user_role)
        db.session.add(role)
        db.session.flush()

        user = User(name="Operador", email=f"op{waste_type.id}@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add(user)
        db.session.flush()

        inventory = Inventory(
            location_id=loc.id, product_id=product.id,
            current_quantity=stock, transit_quantity=0.0, min_stock=20.0,
        )
        db.session.add(inventory)
        db.session.flush()

        movement = Movement(
            type="TRASLADO",
            origin_location_id=loc_origin.id,
            destination_location_id=loc.id,
            status="COMPLETED",
            user_id=user.id,
        )
        db.session.add(movement)
        db.session.flush()

        detail = MovementDetail(
            movement_id=movement.id,
            product_id=product.id,
            lot_number="L-001",
            quantity=stock,
            received_quantity=stock,
            missing_quantity=0.00,
            expiration_date=lot_expiration,
        )
        db.session.add(detail)
        db.session.commit()

        return {
            "location": loc,
            "product": product,
            "waste_type": waste_type,
            "user": user,
            "user_id": user.id,
            "inventory": inventory,
            "movement": movement,
            "origin": loc_origin,
            "product_id": product.id,
            "location_id": loc.id,
        }

    def _register(self, env, items, waste_type_id=None, notes="Prueba",
                  evidence_url=None, user_id=None, location_id=None):
        """Envuelve el servicio de registro con defaults del escenario."""
        default_type_id = waste_type_id or env["waste_type"].id
        items = [
            dict(item, **({"waste_type_id": default_type_id}
                          if item.get("waste_type_id") is None else {}))
            for item in items
        ]
        return register_waste(
            user_id=user_id or env["user_id"],
            location_id=location_id or env["location_id"],
            items=items,
            evidence_url=evidence_url,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # 1) MERMA APROBADA
    # ------------------------------------------------------------------
    def test_merma_aprobada_descuenta_stock_y_registra_audit(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        self.assertEqual(float(inv.current_quantity), 45.0)
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(waste.status, "APROBADO")
        self.assertEqual(float(waste.total_quantity), 5.0)
        audit = AuditLog.query.filter_by(affected_table="inventory", action="MERMA").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.changed_data["lot_number"], "L-001")
        self.assertEqual(audit.changed_data["quantity_changed"], -5.0)

    def test_merma_aprobada_libera_disponibilidad_del_lote(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 10.0}
        ])
        self.assertTrue(res["success"])
        lots = RegisterWasteRepository.get_product_lots(env["product"].id, env["location"].id)
        self.assertEqual(float(lots[0]["quantity"]), 40.0)

    def test_merma_aprobada_por_aprobador_resta_del_lote(self):
        # Flujo PENDIENTE -> APROBADO (aprobación): el audit de aprobación no
        # lleva lot_number, pero el lote igual debe restar la cantidad aprobada.
        # Además, desde que queda PENDIENTE la cantidad ya reduce la
        # disponibilidad del lote (está "en proceso"); al aprobar se conserva
        # el mismo saldo (no descuenta dos veces).
        env = self._seed_env(stock=100.0, waste_limit=20.0, waste_type=WasteType(
            name="Ruptura de cadena de frio", code="TEMPERATURA",
            severity="CRITICA", requires_approval=True,
            applies_central=True, is_active=True))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 30.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        lots = RegisterWasteRepository.get_product_lots(env["product"].id, env["location"].id)
        self.assertEqual(float(lots[0]["quantity"]), 70.0)

        waste = Waste.query.get(res["waste_id"])
        waste.status = "APROBADO"
        db.session.commit()
        db.session.expunge_all()
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 70.0)

    def test_merma_aprobada_parcial_resta_solo_lineas_aprobadas(self):
        # APROBADO_PARCIAL: solo la línea con status APROBADO descuenta del lote;
        # antes este estado no se contaba y la disponibilidad quedaba inflada.
        env = self._seed_env(stock=100.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 30.0}
        ])
        self.assertTrue(res["success"])
        db.session.expunge_all()

        waste = Waste.query.get(res["waste_id"])
        waste.status = "APROBADO_PARCIAL"
        detail = WasteDetail.query.filter_by(waste_id=waste.id).first()
        detail.status = "APROBADO"
        db.session.commit()
        db.session.expunge_all()

        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 70.0)

    # ------------------------------------------------------------------
    # 2) MERMA PENDIENTE
    # ------------------------------------------------------------------
    def test_merma_pendiente_por_tipo_sensible_no_descuenta_y_notifica(self):
        env = self._seed_env(stock=100.0, waste_type=WasteType(
            name="Ruptura de cadena de frio", code="TEMPERATURA",
            severity="CRITICA", requires_approval=True,
            applies_central=True, is_active=True))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        self.assertEqual(float(inv.current_quantity), 100.0)
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(waste.status, "PENDIENTE")
        audit = AuditLog.query.filter_by(affected_table="waste", action="MERMA").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.severity, "ALERTA")
        notif = Notification.query.filter_by(type="MERMA_PENDIENTE").first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.waste_id, waste.id)
        self.assertIn(str(waste.id), notif.message)

    def test_merma_pendiente_por_cantidad_alcanza_waste_limit(self):
        env = self._seed_env(stock=100.0, waste_limit=10.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 10.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        self.assertEqual(float(inv.current_quantity), 100.0)

    def test_merma_aprobada_cuando_esta_bajo_el_waste_limit(self):
        env = self._seed_env(stock=100.0, waste_limit=30.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    # ------------------------------------------------------------------
    # 3) ANTI DOBLE-CARGO EN UN MISMO TICKET
    # ------------------------------------------------------------------
    def test_anti_doble_cargo_mismo_producto_rechaza_exceso(self):
        env = self._seed_env(stock=5.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 3.0},
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 3.0},
        ])
        self.assertFalse(res["success"])
        self.assertIn("Stock insuficiente", res["message"])
        db.session.expunge_all()
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        self.assertEqual(float(inv.current_quantity), 5.0)

    def test_anti_doble_cargo_mismo_lote_rechaza_exceso_acumulado(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        db.session.add(MovementDetail(
            movement_id=env["movement"].id,
            product_id=env["product_id"],
            lot_number="L-002",
            quantity=60.0,
            received_quantity=60.0,
            missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=15),
        ))
        db.session.execute(
            text("UPDATE movement_details SET quantity=40.0, received_quantity=40.0 "
                 "WHERE lot_number='L-001'")
        )
        db.session.commit()
        # L-001 queda con saldo 40; dos líneas de 30 en el mismo lote suman 60 > 40.
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 30.0},
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 30.0},
        ])
        self.assertFalse(res["success"])
        self.assertIn("acumulado", res["message"])

    def test_dos_productos_distintos_suman_sin_bloquearse(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        product_b = Product(name="Papa", sku="PAP-1", unit_of_measure="kg",
                            waste_limit=20.0, is_active=True)
        db.session.add(product_b)
        db.session.flush()
        inv_b = Inventory(location_id=env["location"].id, product_id=product_b.id,
                          current_quantity=10.0, transit_quantity=0.0, min_stock=5.0)
        db.session.add(inv_b)
        move_b = Movement(
            type="TRASLADO",
            origin_location_id=env["origin"].id,
            destination_location_id=env["location"].id,
            status="COMPLETED",
            user_id=env["user_id"],
        )
        db.session.add(move_b)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=move_b.id,
            product_id=product_b.id,
            lot_number="L-002",
            quantity=10.0,
            received_quantity=10.0,
            missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=15),
        ))
        db.session.commit()
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0},
            {"product_id": product_b.id, "lot_number": "L-002", "quantity": 4.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    # ------------------------------------------------------------------
    # 4) VALIDACIONES DE LOTES / STOCK
    # ------------------------------------------------------------------
    def test_lote_insuficiente_rechaza_con_saldo(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        # L-001 entra con 100; se reparte: L-001->60 y L-002->40, así el saldo
        # del lote es menor que el stock del producto y se prueba la rama del lote.
        db.session.add(MovementDetail(
            movement_id=env["movement"].id,
            product_id=env["product_id"],
            lot_number="L-002",
            quantity=40.0,
            received_quantity=40.0,
            missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=15),
        ))
        db.session.commit()
        db.session.execute(
            text("UPDATE movement_details SET quantity=60.0, received_quantity=60.0 "
                 "WHERE lot_number='L-001'")
        )
        db.session.commit()
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 90.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("solo dispone", res["message"])

    def test_lote_recibido_en_varias_partidas_con_vencimientos_suma_todo(self):
        # El lote L-001 entra por DOS partidas con vencimientos distintos
        # (300 + 100 = 400). La derivación genérica sobrescribe el lote y solo
        # vería una partida; acá debe sumarse la disponibilidad completa.
        env = self._seed_env(stock=400.0, waste_limit=500.0)
        db.session.execute(
            text("UPDATE movement_details SET quantity=300.0, received_quantity=300.0 "
                 "WHERE lot_number='L-001'")
        )
        db.session.add(MovementDetail(
            movement_id=env["movement"].id,
            product_id=env["product_id"],
            lot_number="L-001",
            quantity=100.0,
            received_quantity=100.0,
            missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=10),
        ))
        db.session.commit()

        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["lot_number"], "L-001")
        self.assertEqual(float(lots[0]["quantity"]), 400.0)

        # 350 exige ver TODAS las partidas del lote (ninguna suelta alcanza).
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 350.0}
        ])
        self.assertTrue(res["success"])
        db.session.expunge_all()
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        self.assertEqual(float(inv.current_quantity), 50.0)

    def test_salida_de_lote_a_otra_sede_resta_disponibilidad(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        out = Movement(type="RETORNO_EMERGENCIA",
                       origin_location_id=env["location_id"],
                       destination_location_id=env["origin"].id,
                       status="COMPLETED", user_id=env["user_id"])
        db.session.add(out)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=out.id, product_id=env["product_id"], lot_number="L-001",
            quantity=30.0, received_quantity=30.0, missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=30)))
        db.session.commit()
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 70.0)

    def test_lote_inexistente_rechaza(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "NO-EXISTE", "quantity": 1.0}
        ])
        self.assertFalse(res["success"])

    def test_producto_sin_inventario_rechaza(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": 99999, "lot_number": "L-001", "quantity": 1.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("No existe inventario", res["message"])

    def test_tipo_inactivo_rechazado(self):
        env = self._seed_env(waste_type=WasteType(
            name="Inactivo", code="BAJA_TEMP",
            severity="MEDIA", requires_approval=False,
            applies_central=False, is_active=False))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 1.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("no es válido", res["message"])

    # ------------------------------------------------------------------
    # 5) PERMISOS POR SEDE
    # ------------------------------------------------------------------
    def test_sede_ajena_rechazada_para_no_admin(self):
        env = self._seed_env(user_role="Operations")
        otra = Location(name="Otra Sede", state="Caracas")
        db.session.add(otra)
        db.session.commit()
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 1.0}
        ], location_id=otra.id)
        self.assertFalse(res["success"])
        self.assertIn("permisos", res["message"].lower())

    def test_fetch_types_sede_ajena_devuelve_403(self):
        env = self._seed_env(user_role="Operations")
        env["user"].locations.append(env["location"])
        otra = Location(name="Otra Sede Tipos", state="Caracas")
        db.session.add(otra)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.get(f"/api/waste/locations/{otra.id}/types")
        self.assertEqual(resp.status_code, 403)
        resp2 = client.get(f"/api/waste/locations/{env['location_id']}/types")
        self.assertEqual(resp2.status_code, 200)

    # ------------------------------------------------------------------
    # 6) MERMA EN SEDE CENTRAL (id=1)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 8) CASOS DE LA PROPUESTA MÓDULO 7 (pruebas de registro de todo tipo)
    # ------------------------------------------------------------------
    def _seed_waste_history(self, env, qty, status, days_ago, code="VENCIDO"):
        """Siembra un ticket de merma histórico para la regla de TIEMPO."""
        wtype = WasteType.query.filter_by(code=code).first()
        if wtype is None:
            wtype = WasteType(name="Vencido", code=code, severity="MEDIA",
                              requires_approval=False, applies_central=False,
                              is_active=True)
            db.session.add(wtype)
            db.session.flush()
        w = Waste(
            location_id=env["location"].id,
            waste_type_id=wtype.id,
            user_id=env["user_id"],
            status=status,
            total_quantity=qty,
            total_cost=0,
            currency="USD",
            notes="historial",
            date=datetime.utcnow() - timedelta(days=days_ago),
        )
        db.session.add(w)
        db.session.commit()
        return w

    def _seed_extra_lot(self, env, sku, name="Insumo Adicional", qty=50.0,
                        lot="L-EXT", waste_limit=20.0):
        """Agrega un producto + lote al MISMO traslado del escenario (no central)."""
        p = Product(name=name, sku=sku, unit_of_measure="kg",
                    waste_limit=waste_limit, is_active=True)
        db.session.add(p)
        db.session.flush()
        inv = Inventory(location_id=env["location"].id, product_id=p.id,
                        current_quantity=qty, transit_quantity=0.0, min_stock=5.0)
        db.session.add(inv)
        db.session.add(MovementDetail(
            movement_id=env["movement"].id,
            product_id=p.id,
            lot_number=lot,
            quantity=qty,
            received_quantity=qty,
            missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=10),
        ))
        db.session.commit()
        return p

    # --- 8.1 Regla de TIEMPO (clasificador) -----------------------------------
    def test_tiempo_normal_justificada_aprueba(self):
        # Historial: 30 kg APROBADOS hace 15 días (tasa 1.0/día) y la última
        # merma (PENDIENTE) hace 20 días. esperado = 1.0*20 = 20, umbral = 30.
        # Registrar 15 kg (por debajo del umbral) debe quedar APROBADO.
        env = self._seed_env(stock=100.0, waste_limit=100.0)
        self._seed_waste_history(env, 30.0, "APROBADO", 15)
        self._seed_waste_history(env, 5.0, "PENDIENTE", 20)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 15.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    def test_tiempo_merma_gigante_en_un_dia_queda_pendiente(self):
        # Historial: 30 kg APROBADOS hace 15 días (tasa 1.0/día) y la última
        # ayer. esperado = 1.0*1 = 1, umbral = 1.5. Registrar 25 kg -> PENDIENTE
        # por regla de tiempo y el stock NO se descuenta.
        env = self._seed_env(stock=150.0, waste_limit=100.0)
        self._seed_waste_history(env, 30.0, "APROBADO", 15)
        self._seed_waste_history(env, 5.0, "PENDIENTE", 1)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 25.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(float(inv.current_quantity), 150.0)

    def test_tiempo_sin_historial_aprueba_por_cantidad(self):
        # Sin historial normal (tasa = 0) la regla de tiempo no aplica.
        env = self._seed_env(stock=100.0, waste_limit=30.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    def test_tiempo_sede_con_menos_de_periodo_base_no_aplica(self):
        # Sede con solo 3 días de historial (por debajo del período base=7):
        # la regla de tiempo NO evalúa y la merma queda APROBADO, aunque
        # supere lo esperado del período transcurrido (15 kg > 4.5 si aplicara).
        env = self._seed_env(stock=100.0, waste_limit=100.0)
        self._seed_waste_history(env, 30.0, "APROBADO", 3)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 15.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    def test_micro_merma_segunda_del_dia_aprueba_con_piso(self):
        # Fix opción A: con piso elapsed=1 la 2ª merma del mismo día se compara
        # contra el esperado de 1 día (tasa=2/30=0.067 -> umbral 0.10), por lo
        # que una micro-merma 0.01 kg queda APROBADO (antes quedaba PENDIENTE).
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        r1 = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ])
        self.assertEqual(r1["status"], "APROBADO")
        r2 = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 0.01}
        ])
        self.assertTrue(r2["success"])
        self.assertEqual(r2["status"], "APROBADO")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(round(float(inv.current_quantity), 2), 97.99)

    # --- 8.2 Multi-lote, acumulado entre tickets y repetido -------------------
    def test_multilote_tres_lineas_mismo_evento(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        p_b = self._seed_extra_lot(env, "SKU-B", name="Papa", qty=50.0, lot="L-B")
        p_c = self._seed_extra_lot(env, "SKU-C", name="Zanahoria", qty=50.0, lot="L-C")
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0},
            {"product_id": p_b.id, "lot_number": "L-B", "quantity": 4.0},
            {"product_id": p_c.id, "lot_number": "L-C", "quantity": 3.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(float(waste.total_quantity), 12.0)
        self.assertEqual(len(waste.details), 3)

    def test_dos_mermas_secuenciales_acumulan_descuento(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        r1 = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertEqual(r1["status"], "APROBADO")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(float(inv.current_quantity), 45.0)
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 45.0)

    def test_dos_mermas_dentro_de_24h_segunda_queda_pendiente(self):
        # Regla de TIEMPO de la propuesta: con sede ya con período base de
        # historial, mismo día / menos de 24h la segunda merma entra PENDIENTE
        # si supera lo esperado en 1 día (piso elapsed=1): r2 = 5 kg con tasa
        # (30+5)/30=1.17 -> umbral 1.75 -> PENDIENTE.
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        self._seed_waste_history(env, 30.0, "APROBADO", 15)
        r1 = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertEqual(r1["status"], "APROBADO")
        r2 = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(r2["success"])
        self.assertEqual(r2["status"], "PENDIENTE")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(float(inv.current_quantity), 45.0)
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        # r1 (5 aprobada) + r2 (5 pendiente) comprometen 10 del lote: 50 - 10 = 40.
        self.assertEqual(float(lots[0]["quantity"]), 40.0)
        audit = AuditLog.query.filter_by(affected_table="inventory", action="MERMA").count()
        self.assertEqual(audit, 1)  # solo la primera descuenta stock

    def test_merma_pendiente_si_consume_disponibilidad_del_lote(self):
        # Regla de "en proceso": aunque la merma PENDIENTE no descuenta el stock
        # físico, sí reduce la disponibilidad del lote (100 - 2 = 98) para que
        # no se puedan registrar nuevas mermas sobre lo ya comprometido.
        env = self._seed_env(stock=100.0, waste_type=WasteType(
            name="Ruptura de cadena de frio", code="TEMPERATURA",
            severity="CRITICA", requires_approval=True,
            applies_central=True, is_active=True))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ])
        self.assertEqual(res["status"], "PENDIENTE")
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 98.0)

    def test_merma_misma_linea_repetida_en_el_ticket_se_suma(self):
        # El validador tolera la misma línea repetida (se acumula) siempre que
        # no exceda el saldo; documenta el comportamiento intencional del API.
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 3.0},
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 4.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(len(waste.details), 2)
        self.assertEqual(float(waste.total_quantity), 7.0)

    # --- 8.3 Foto (evidencia) siempre opcional --------------------------------
    def test_foto_opcional_presente_se_guarda(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ], evidence_url="https://i.imgbb.com/x.jpg")
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(waste.evidence_url, "https://i.imgbb.com/x.jpg")

    def test_foto_opcional_ausente_no_bloquea(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ], evidence_url=None)
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        self.assertIsNone(waste.evidence_url)

    def test_foto_vacia_se_guarda_como_nulo(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ], evidence_url="")
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        self.assertIsNone(waste.evidence_url)

    def test_foto_opcional_por_item_se_guarda_en_linea(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0,
             "evidence_url": "https://i.imgbb.com/item1.jpg"}
        ], evidence_url="https://i.imgbb.com/general.jpg")
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        self.assertEqual(waste.evidence_url, "https://i.imgbb.com/general.jpg")
        detail = WasteDetail.query.filter_by(waste_id=waste.id).first()
        self.assertEqual(detail.evidence_url, "https://i.imgbb.com/item1.jpg")

    def test_foto_opcional_por_item_ausente_queda_nula(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ])
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        detail = WasteDetail.query.filter_by(waste_id=waste.id).first()
        self.assertIsNone(detail.evidence_url)

    def test_payload_item_con_evidencia_no_url_rechazado_por_validador(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        data = {
            "location_id": env["location_id"],
            "waste_type_id": env["waste_type"].id,
            "notes": "Prueba",
            "items": [
                {"product_id": env["product_id"], "lot_number": "L-001",
                 "quantity": 2.0, "evidence_url": 12345}
            ],
        }
        res = validate_register_waste_payload(data)
        self.assertFalse(res["is_valid"])
        self.assertIn("item_0_evidence_url", res["errors"])

    def test_fotos_multiple_por_item_se_guardan_en_tabla(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0,
             "evidence_urls": ["https://i.imgbb.com/f1.jpg",
                               "https://i.imgbb.com/f2.jpg",
                               "https://i.imgbb.com/f3.jpg"],
             "evidence_url": "https://i.imgbb.com/f1.jpg"}
        ], evidence_url="https://i.imgbb.com/general.jpg")
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        detail = WasteDetail.query.filter_by(waste_id=waste.id).first()
        self.assertEqual(detail.evidence_url, "https://i.imgbb.com/f1.jpg")
        photos = WasteDetailPhoto.query.filter_by(waste_detail_id=detail.id).all()
        self.assertEqual(len(photos), 3)
        self.assertEqual([p.photo_url for p in sorted(photos, key=lambda p: p.position)],
                         ["https://i.imgbb.com/f1.jpg", "https://i.imgbb.com/f2.jpg",
                          "https://i.imgbb.com/f3.jpg"])
        self.assertEqual([p.position for p in sorted(photos, key=lambda p: p.position)], [1, 2, 3])

    def test_fotos_multiple_sin_evidencia_no_crea_filas(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 2.0}
        ])
        self.assertTrue(res["success"])
        waste = Waste.query.get(res["waste_id"])
        detail = WasteDetail.query.filter_by(waste_id=waste.id).first()
        self.assertIsNone(detail.evidence_url)
        photos = WasteDetailPhoto.query.filter_by(waste_detail_id=detail.id).all()
        self.assertEqual(len(photos), 0)

    def test_payload_item_con_evidence_urls_invalidas_rechazado(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        data = {
            "location_id": env["location_id"],
            "waste_type_id": env["waste_type"].id,
            "notes": "Prueba",
            "items": [
                {"product_id": env["product_id"], "lot_number": "L-001",
                 "quantity": 2.0, "evidence_urls": "no-es-una-lista"}
            ],
        }
        res = validate_register_waste_payload(data)
        self.assertFalse(res["is_valid"])
        self.assertIn("item_0_evidence_urls", res["errors"])
        data["items"][0]["evidence_urls"] = ["https://i.imgbb.com/ok.jpg", 123]
        res2 = validate_register_waste_payload(data)
        self.assertFalse(res2["is_valid"])
        self.assertIn("item_0_evidence_urls", res2["errors"])

    def test_evidence_rechaza_archivo_no_imagen(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.post("/api/waste/evidence",
                           data={"image": (io.BytesIO(b"hola mundo"), "nota.txt")},
                           content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("imagen", data["message"].lower())

    def test_evidence_rechaza_archivo_demasiado_grande(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        big = io.BytesIO(b"x" * (5 * 1024 * 1024 + 1))
        resp = client.post("/api/waste/evidence",
                           data={"image": (big, "foto.jpg")},
                           content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("5 MB", data["message"])

    # --- 8.4 Severidad de auditoría según rango de stock ----------------------
    def test_severidad_alerta_cuando_queda_bajo_min_stock(self):
        env = self._seed_env(stock=25.0, waste_limit=30.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 6.0}
        ])
        self.assertEqual(res["status"], "APROBADO")
        audit = AuditLog.query.filter_by(affected_table="inventory", action="MERMA").first()
        self.assertEqual(audit.severity, "ALERTA")  # 19 <= min_stock(20)

    def test_severidad_critico_cuando_agota_stock(self):
        env = self._seed_env(stock=25.0, waste_limit=30.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 25.0}
        ])
        self.assertEqual(res["status"], "APROBADO")
        audit = AuditLog.query.filter_by(affected_table="inventory", action="MERMA").first()
        self.assertEqual(audit.severity, "CRITICO")  # 0 <= 0

    # --- 8.5 Formulario: sede única vs múltiples sedes ------------------------
    def test_form_data_una_sola_sede_la_devuelve(self):
        env = self._seed_env(user_role="Operations")
        env["user"].locations.append(env["location"])
        db.session.commit()
        locations, is_admin, waste_types = get_form_data(env["user_id"])
        self.assertFalse(is_admin)
        self.assertEqual([l.id for l in locations], [env["location"].id])
        self.assertEqual(len(waste_types), 1)

    def test_form_data_multisede_solo_asignadas(self):
        env = self._seed_env(user_role="Operations")
        otra = Location(name="Otra Sede", state="Caracas")
        db.session.add(otra)
        db.session.flush()
        tercera = Location(name="Tercera Sede", state="Caracas")
        db.session.add(tercera)
        db.session.flush()
        env["user"].locations.append(env["location"])
        env["user"].locations.append(otra)
        db.session.commit()
        locations, is_admin, waste_types = get_form_data(env["user_id"])
        ids = sorted(l.id for l in locations)
        self.assertEqual(ids, sorted([env["location"].id, otra.id]))
        self.assertNotIn(tercera.id, ids)

    # --- 8.6 Catálogo de tipos y roles ----------------------------------------
    def test_catalogo_siete_tipos_sin_llego_danado(self):
        catalog = [
            ("Vencido", "VENCIDO"),
            ("Dañado/Averiado", "DANADO"),
            ("Cocina - Merma por error", "COCINA_ERROR"),
            ("Derramado/Contaminado", "DERRAME"),
            ("Ruptura de cadena de frio", "TEMPERATURA"),
            ("Sospecha de robo/extravío", "ROBO_SOSPECHA"),
            ("Extraviado sin motivo", "EXTRAVIO"),
        ]
        types = []
        for name, code in catalog:
            t = WasteType(name=name, code=code, severity="MEDIA",
requires_approval=code in ("TEMPERATURA", "ROBO_SOSPECHA"),
            applies_central=code in ("VENCIDO", "TEMPERATURA", "ROBO_SOSPECHA"),
                          is_active=True)
            db.session.add(t)
            types.append(t)
        db.session.commit()
        self.assertEqual(len(types), 7)
        codes = {t.code for t in types}
        self.assertNotIn("LLEGADO_DANADO", codes)

    def test_finance_no_es_rol_operativo(self):
        from app.waste.routes.register_waste_routes import OPERATIVE_ROLES
        self.assertNotIn("finance", OPERATIVE_ROLES)

    # --- 8.7 Rutas HTTP: login, flujo e2e y bloqueo de rol --------------------
    def test_ruta_nueva_merma_requiere_login(self):
        resp = self.app.test_client().get("/waste/merma/new", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))

    def test_ruta_crear_merma_requiere_login(self):
        resp = self.app.test_client().post(
            "/waste/merma/new",
            json={"location_id": 1, "waste_type_id": 1, "items": [], "notes": "x"},
            follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))

    def test_e2e_http_registro_aprobado_como_admin(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp_get = client.get("/waste/merma/new")
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn("Registro de Merma", resp_get.get_data(as_text=True))

        payload = {
            "location_id": env["location_id"],
            "items": [{"product_id": env["product_id"], "lot_number": "L-001",
                       "quantity": 5.0, "waste_type_id": env["waste_type"].id}],
            "notes": "Vencido",
        }
        resp = client.post("/waste/merma/new", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "APROBADO")
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(float(inv.current_quantity), 45.0)

    def test_e2e_http_request_id_duplicado_no_crea_doble_merma(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])

        payload = {
            "location_id": env["location_id"],
            "items": [{"product_id": env["product_id"], "lot_number": "L-001",
                       "quantity": 5.0, "waste_type_id": env["waste_type"].id}],
            "notes": "Con request_id",
            "request_id": "req-http-abc",
        }

        def reset_submit_lock():
            with client.session_transaction() as sess:
                sess["last_waste_submit_time"] = 0

        reset_submit_lock()
        r1 = client.post("/waste/merma/new", json=payload)
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json()
        self.assertTrue(d1["success"])
        self.assertFalse(d1.get("duplicate"))

        reset_submit_lock()
        r2 = client.post("/waste/merma/new", json=payload)
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json()
        self.assertTrue(d2["success"])
        self.assertTrue(d2.get("duplicate"))
        self.assertEqual(d2["waste_id"], d1["waste_id"])

        db.session.expunge_all()
        self.assertEqual(
            Waste.query.filter_by(request_id="req-http-abc").count(), 1
        )
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        # El stock se descuenta UNA sola vez (45.0), no por cada reintento.
        self.assertEqual(float(inv.current_quantity), 45.0)
        self.assertEqual(
            AuditLog.query.filter_by(affected_table="inventory",
                                     action="MERMA").count(), 1
        )

        # Un request_id distinto SÍ crea una merma nueva (sin interferencias).
        payload2 = dict(payload, request_id="req-http-xyz")
        reset_submit_lock()
        r3 = client.post("/waste/merma/new", json=payload2)
        self.assertEqual(r3.status_code, 200)
        d3 = r3.get_json()
        self.assertTrue(d3["success"])
        self.assertFalse(d3.get("duplicate"))
        self.assertNotEqual(d3["waste_id"], d1["waste_id"])

    def test_e2e_http_validacion_devuelve_400(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.post("/waste/merma/new", json={
            "location_id": env["location_id"],
            "waste_type_id": env["waste_type"].id,
            "items": [{"product_id": env["product_id"], "lot_number": "L-001",
                       "quantity": 0}],
            "notes": "",
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("item_0_quantity", data["errors"])

    def test_e2e_http_finance_bloqueado_y_sin_descuento(self):
        env = self._seed_env()
        role_f = Role(id=6, name="Finance")
        db.session.add(role_f)
        db.session.flush()
        user_f = User(name="Finanzas", email="fin-waste@test.com",
                      password_hash="x", role_id=role_f.id)
        db.session.add(user_f)
        db.session.flush()
        user_f.locations.append(env["location"])
        db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user_f.id)
        resp = client.post(
            "/waste/merma/new",
            json={"location_id": env["location_id"],
                  "waste_type_id": env["waste_type"].id,
                  "items": [{"product_id": env["product_id"], "lot_number": "L-001",
                             "quantity": 2.0}],
                  "notes": "x"},
            follow_redirects=False)
        # require_roles: Finance NO está en OPERATIVE_ROLES -> redirige a login
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.headers.get("Location", ""))
        db.session.expunge_all()
        inv = Inventory.query.filter_by(product_id=env["product_id"],
                                        location_id=env["location_id"]).first()
        self.assertEqual(float(inv.current_quantity), 100.0)

    # ------------------------------------------------------------------
    # 8.8) TIPO VENCIDO: solo lotes ya vencidos (idea registrada)
    # ------------------------------------------------------------------
    def test_vencido_permite_lote_ya_vencido(self):
        # _seed_env por defecto crea el lote con vencimiento ya pasado.
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    def test_vencido_rechaza_lote_vigente(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today() + timedelta(days=365))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("VENCIDO", res["message"])

    def test_vencido_rechaza_lote_sin_fecha(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        db.session.add(MovementDetail(
            movement_id=env["movement"].id,
            product_id=env["product_id"],
            lot_number="L-SIN-VEN",
            quantity=10.0,
            received_quantity=10.0,
            missing_quantity=0.00,
            expiration_date=None,
        ))
        db.session.commit()
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-SIN-VEN", "quantity": 5.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("VENCIDO", res["message"])

    def test_vencido_lote_multi_partida_usa_vencimiento_minimo(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        db.session.add(MovementDetail(
            movement_id=env["movement"].id, product_id=env["product_id"],
            lot_number="L-001", quantity=80.0, received_quantity=80.0,
            missing_quantity=0.00,
            expiration_date=date.today() + timedelta(days=365)))
        db.session.commit()
        lots = RegisterWasteRepository.get_product_lots(env["product_id"], env["location_id"])
        self.assertEqual(float(lots[0]["quantity"]), 130.0)
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 10.0}
        ])
        self.assertTrue(res["success"])
        vencidos = RegisterWasteRepository.get_expired_lots(env["location_id"])
        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0]["lot_number"], "L-001")

    def test_otro_tipo_permite_lote_vigente(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today() + timedelta(days=365),
                             waste_type=WasteType(
                                 name="Dañado/Averiado", code="DANADO",
                                 severity="MEDIA", requires_approval=False,
                                 applies_central=False, is_active=True))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")

    def test_vencido_rechazado_por_api_http(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today() + timedelta(days=365))
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.post("/waste/merma/new", json={
            "location_id": env["location_id"],
            "items": [{"product_id": env["product_id"], "lot_number": "L-001",
                       "quantity": 5.0, "waste_type_id": env["waste_type"].id}],
            "notes": "Vencido",
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("VENCIDO", data["message"])

    def test_vencido_rechaza_lote_que_vence_hoy(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today())
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("VENCIDO", res["message"])

    def test_vencido_permite_lote_vencido_ayer(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today() - timedelta(days=1))
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])

    def test_vencido_permite_lote_sin_fecha_solo_para_otro_tipo(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             waste_type=WasteType(
                                 name="Dañado", code="DANADO", severity="MEDIA",
                                 requires_approval=False,
                                 applies_central=False, is_active=True),
                             lot_expiration=date.today() + timedelta(days=10))
        res = self._register(env, [
            {"product_id": env["product_id"], "lot_number": "L-001", "quantity": 5.0}
        ])
        self.assertTrue(res["success"])

    # ------------------------------------------------------------------
    # 6) MERMA EN SEDE CENTRAL (id=1)
    # ------------------------------------------------------------------
    def test_merma_central_con_tipo_sensible(self):
        central = Location.query.get(1)
        if central is None:
            central = Location(id=1, name="Almacén Central", state="Distrito Capital")
            db.session.add(central)
            db.session.flush()

        product = Product(name="Carne", sku="CAR-1", unit_of_measure="kg",
                          waste_limit=10.0, is_active=True)
        db.session.add(product)
        db.session.flush()

        waste_types = [
            WasteType(name="Ruptura de cadena de frio", code="TEMPERATURA",
                      severity="CRITICA", requires_approval=True,
                      applies_central=True, is_active=True),
            WasteType(name="Sospecha de robo/extravío", code="ROBO_SOSPECHA",
                      severity="CRITICA", requires_approval=True,
                      applies_central=True, is_active=True),
        ]
        db.session.add_all(waste_types)
        db.session.flush()
        env_type = waste_types[0]

        role = Role(id=1, name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Admin", email="admin-waste@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add(user)
        db.session.flush()

        inv = Inventory(location_id=1, product_id=product.id,
                        current_quantity=50.0, transit_quantity=0.0, min_stock=10.0)
        db.session.add(inv)
        db.session.flush()

        supplier = Supplier(name="Prov Central", tax_id="J-1")
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(supplier_id=supplier.id,
                            status="COMPLETED", user_id=user.id,
                            total_amount=0, exchange_rate=1.0,
                            invoice_url="http://x/inv.pdf")
        db.session.add(purchase)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=purchase.id, product_id=product.id, lot_number="L-CEN",
            quantity=50.0, foreign_price=4.0,
            expiration_date=date(2027, 2, 1)))
        db.session.commit()

        res = register_waste(
            user_id=user.id, location_id=1,
            items=[{"product_id": product.id, "lot_number": "L-CEN", "quantity": 3.0,
                    "waste_type_id": env_type.id}],
            notes="Cadena de frio",
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")

        types = RegisterWasteRepository.get_waste_types()
        applies = {t.code for t in types if t.applies_central}
        self.assertEqual(applies, {"TEMPERATURA", "ROBO_SOSPECHA"})

    def test_central_rechaza_tipo_no_aplicable_en_registro(self):
        env = self._seed_central_env()
        db.session.add(WasteType(name="Dañado", code="DANADO", severity="MEDIA",
                                 requires_approval=False, applies_central=False,
                                 is_active=True))
        db.session.commit()
        tipo = WasteType.query.filter_by(code="DANADO").first()
        res = register_waste(
            user_id=env["user_id"], location_id=1,
            items=[{"product_id": env["product"].id, "lot_number": env["lot"],
                    "quantity": 3.0, "waste_type_id": tipo.id}],
            notes="Dañado",
        )
        self.assertFalse(res["success"])
        self.assertIn("no aplica a la Sede Central", res["message"])

    def test_central_vencido_permite_por_defecto(self):
        env = self._seed_central_env(lot_expiration=date.today() - timedelta(days=30))
        env["waste_type"].applies_central = False
        db.session.commit()
        res = register_waste(
            user_id=env["user_id"], location_id=1,
            items=[{"product_id": env["product"].id, "lot_number": env["lot"],
                    "quantity": 3.0, "waste_type_id": env["waste_type"].id}],
            notes="Vencido",
        )
        self.assertTrue(res["success"])
        self.assertNotIn("no aplica a la Sede Central", (res.get("message") or ""))

        vencidos = RegisterWasteRepository.get_expired_lots(1)
        self.assertEqual(len(vencidos), 1)

    # ------------------------------------------------------------------
    # 7) VALIDADOR DE PAYLOAD
    # ------------------------------------------------------------------
    def test_validator_items_vacios(self):
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        v = validate_register_waste_payload({
            "location_id": 1, "waste_type_id": 1, "items": [], "notes": "x"
        })
        self.assertFalse(v["is_valid"])
        self.assertIn("items", v["errors"])

    def test_validator_lote_faltante(self):
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        v = validate_register_waste_payload({
            "location_id": 1, "waste_type_id": 1,
            "items": [{"product_id": 1, "quantity": 2.0}], "notes": "x"
        })
        self.assertFalse(v["is_valid"])
        self.assertIn("item_0_lot_number", v["errors"])

    def test_validator_cantidad_invalida(self):
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        v = validate_register_waste_payload({
            "location_id": 1, "waste_type_id": 1,
            "items": [{"product_id": 1, "lot_number": "L-1", "quantity": 0}], "notes": "x"
        })
        self.assertFalse(v["is_valid"])
        self.assertIn("item_0_quantity", v["errors"])

    def test_validator_rechaza_cantidad_no_finita_y_bool(self):
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        base = {"location_id": 1, "waste_type_id": 1, "notes": "x"}
        for bad in [float("nan"), float("inf"), float("-inf"), True]:
            v = validate_register_waste_payload({
                **base,
                "items": [{"product_id": 1, "lot_number": "L-1", "quantity": bad}],
            })
            self.assertFalse(v["is_valid"])
            self.assertIn("item_0_quantity", v["errors"])

    def test_validator_motivo_obligatorio(self):
        from app.waste.requests.register_waste_validators import validate_register_waste_payload
        v = validate_register_waste_payload({
            "location_id": 1, "waste_type_id": 1,
            "items": [{"product_id": 1, "lot_number": "L-1", "quantity": 1.0}],
            "notes": "   "
        })
        self.assertFalse(v["is_valid"])
        self.assertIn("notes", v["errors"])

    # ------------------------------------------------------------------
    # 8.9) SEDE CENTRAL: disponibilidad por lotes y VENCIDO aplicable.
    # ------------------------------------------------------------------
    def _seed_central_env(self, stock=100.0, waste_limit=20.0, lot_qty=100.0,
                          lot="L-CEN", lot_expiration=None,
                          code="VENCIDO", requires_approval=False):
        if lot_expiration is None:
            lot_expiration = date.today() - timedelta(days=60)
        central = Location.query.get(1)
        if central is None:
            central = Location(id=1, name="Almacén Central", state="Distrito Capital")
            db.session.add(central)
            db.session.flush()

        product = Product(name="Tomate Central", sku=f"TOMC-{lot}",
                          unit_of_measure="kg", waste_limit=waste_limit,
                          is_active=True)
        db.session.add(product)
        db.session.flush()

        wt = WasteType(name="Central Test", code=code, severity="MEDIA",
                       requires_approval=requires_approval,
                       applies_central=True, is_active=True)
        db.session.add(wt)
        db.session.flush()

        role = Role(id=1, name="Administrator")
        db.session.add(role)
        db.session.flush()
        user = User(name="Admin Central", email=f"admin-cen-{wt.id}@test.com",
                    password_hash="x", role_id=role.id)
        db.session.add(user)
        db.session.flush()

        inv = Inventory(location_id=1, product_id=product.id,
                        current_quantity=stock, transit_quantity=0.0,
                        min_stock=20.0)
        db.session.add(inv)
        db.session.flush()

        supplier = Supplier(name="Prov Central", tax_id=f"J-C-{wt.id}")
        db.session.add(supplier)
        db.session.flush()
        purchase = Purchase(supplier_id=supplier.id, status="COMPLETED",
                            user_id=user.id, total_amount=0, exchange_rate=1.0,
                            invoice_url="http://x/inv.pdf")
        db.session.add(purchase)
        db.session.flush()
        db.session.add(PurchaseDetail(
            purchase_id=purchase.id, product_id=product.id, lot_number=lot,
            quantity=lot_qty, foreign_price=4.0, expiration_date=lot_expiration))
        db.session.commit()

        return {"location_id": 1, "product": product, "waste_type": wt,
                "user_id": user.id, "lot": lot}

    def _add_product(self, env, name="Cebolla", sku="CEB", waste_limit=100.0,
                     stock=100.0, lot="L-002"):
        """Añade un segundo producto al mismo escenario (misma sede y usuario)."""
        p = Product(name=name, sku=f"{sku}-{env['waste_type'].id}",
                    unit_of_measure="kg", waste_limit=waste_limit, is_active=True)
        db.session.add(p)
        db.session.flush()
        inv = Inventory(location_id=env["location"].id, product_id=p.id,
                        current_quantity=stock, transit_quantity=0.0,
                        min_stock=20.0)
        db.session.add(inv)
        db.session.flush()
        db.session.add(MovementDetail(
            movement_id=env["movement"].id, product_id=p.id, lot_number=lot,
            quantity=stock, received_quantity=stock, missing_quantity=0.00,
            expiration_date=date.today() - timedelta(days=30)))
        db.session.commit()
        return p

    def test_central_lote_con_compra_no_bloquea_la_merma(self):
        env = self._seed_central_env(stock=100.0, waste_limit=20.0, lot_qty=100.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": env["lot"],
             "quantity": 50.0}
        ])
        # 50 > límite (20) -> novedad LIMITE, NO bloqueo ni confusión con
        # la disponibilidad del lote (100 disponibles).
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        self.assertNotIn("solo dispone", res["message"].lower())
        nov = res["novedades"].get(str(env["product"].id), {})
        self.assertIn("LIMITE", nov.get("motivos", []))

    def test_central_mensaje_lote_muestra_contexto_del_stock(self):
        env = self._seed_central_env(stock=100.0, waste_limit=20.0, lot_qty=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": env["lot"],
             "quantity": 50.0}
        ])
        self.assertFalse(res["success"])
        self.assertIn("solo dispone de 20.00 unidades", res["message"])
        self.assertIn("disponible total en la sede: 100.00", res["message"])

    def test_vencido_aparece_en_tipos_de_central_api(self):
        env = self._seed_central_env()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.get("/api/waste/locations/1/types")
        self.assertEqual(resp.status_code, 200)
        codes = [t["code"] for t in resp.get_json()["types"]]
        self.assertIn("VENCIDO", codes)

    def test_vencido_central_aparece_por_defecto(self):
        env = self._seed_central_env()
        env["waste_type"].applies_central = False
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        central = client.get("/api/waste/locations/1/types").get_json()
        codes = [t["code"] for t in central["types"]]
        self.assertIn("VENCIDO", codes)
        for t in central["types"]:
            self.assertNotIn("DANADO", t["code"])

    def test_vencido_central_aparece_con_parametro(self):
        env = self._seed_central_env()
        env["waste_type"].applies_central = False
        db.session.add(AppParameter(
            key="VENCIDO_APLICA_CENTRAL", value="true",
            description="Permite VENCIDO en Almacén Central"))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        central = client.get("/api/waste/locations/1/types").get_json()
        codes = [t["code"] for t in central["types"]]
        self.assertIn("VENCIDO", codes)

    def test_vencido_central_parametro_false_igual_aparece(self):
        env = self._seed_central_env()
        env["waste_type"].applies_central = False
        db.session.add(AppParameter(
            key="VENCIDO_APLICA_CENTRAL", value="false",
            description="Desactiva VENCIDO en Almacén Central"))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        central = client.get("/api/waste/locations/1/types").get_json()
        codes = [t["code"] for t in central["types"]]
        self.assertIn("VENCIDO", codes)

    def test_banner_incluye_central_por_defecto(self):
        env = self._seed_central_env(lot="L-CEN")
        env["waste_type"].applies_central = False
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        page = client.get("/waste/merma/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Almacén Central", page.get_data(as_text=True))
        self.assertIn("L-CEN", page.get_data(as_text=True))

    def test_banner_incluye_central_con_parametro(self):
        env = self._seed_central_env(lot="L-CEN")
        env["waste_type"].applies_central = False
        db.session.add(AppParameter(
            key="VENCIDO_APLICA_CENTRAL", value="true",
            description="Permite VENCIDO en Almacén Central"))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        page = client.get("/waste/merma/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Almacén Central", page.get_data(as_text=True))
        self.assertIn("L-CEN", page.get_data(as_text=True))

    def test_banner_incluye_central_si_tipo_aplica(self):
        env = self._seed_central_env(lot="L-CEN")
        env["waste_type"].applies_central = True
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        page = client.get("/waste/merma/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("L-CEN", page.get_data(as_text=True))

    def test_tipo_no_aplicable_a_central_se_omite_y_si_aplica_en_sucursal(self):
        env = self._seed_central_env()
        db.session.add(WasteType(name="Dañado", code="DANADO", severity="MEDIA",
                                 requires_approval=False,
                                 applies_central=False, is_active=True))
        sucursal = Location(name="Sucursal Noreste", state="Caracas")
        db.session.add(sucursal)
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        central = client.get("/api/waste/locations/1/types").get_json()
        self.assertEqual(
            [t["code"] for t in central["types"] if t["code"] == "DANADO"], [])
        sucursal_types = client.get(
            f"/api/waste/locations/{sucursal.id}/types").get_json()
        self.assertIn("DANADO", [t["code"] for t in sucursal_types["types"]])
        self.assertIn("VENCIDO", [t["code"] for t in sucursal_types["types"]])

    def test_requires_approval_expuesto_en_tipos_api(self):
        env = self._seed_central_env()
        db.session.add(WasteType(name="Cadena de frio", code="TEMPERATURA",
                                 severity="CRITICA", requires_approval=True,
                                 applies_central=True, is_active=True))
        db.session.commit()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        types = client.get("/api/waste/locations/1/types").get_json()["types"]
        by_code = {t["code"]: t for t in types}
        self.assertIn("requires_approval", by_code["VENCIDO"])
        self.assertFalse(by_code["VENCIDO"]["requires_approval"])
        self.assertTrue(by_code["TEMPERATURA"]["requires_approval"])

    # ------------------------------------------------------------------
    # 8.10) NOVEDADES POR PRODUCTO/MOTIVO (audios 2, 3 y 5)
    # ------------------------------------------------------------------
    def test_motivos_por_producto_solo_marca_el_que_excede(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        otro = self._add_product(env, waste_limit=100.0, lot="L-002")
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001",
             "quantity": 30.0},
            {"product_id": otro.id, "lot_number": "L-002", "quantity": 5.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        nov = res["novedades"]
        # El que excede su límite lleva LIMITE; el otro solo la etiqueta VENCIDO.
        self.assertIn(str(env["product"].id), nov)
        self.assertIn("VENCIDO", nov[str(env["product"].id)]["motivos"])
        self.assertIn("LIMITE", nov[str(env["product"].id)]["motivos"])
        self.assertIn(str(otro.id), nov)
        self.assertEqual(nov[str(otro.id)]["motivos"], ["VENCIDO"])
        self.assertNotIn("LIMITE", nov[str(otro.id)]["motivos"])

    def test_tipo_sensible_marca_todos_los_productos_con_tipo(self):
        env = self._seed_env(
            stock=100.0, waste_limit=20.0,
            waste_type=WasteType(name="Cadena de frio", code="TEMPERATURA",
                                 severity="CRITICA", requires_approval=True,
                                 applies_central=False, is_active=True))
        otro = self._add_product(env, lot="L-002")
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001",
             "quantity": 5.0},
            {"product_id": otro.id, "lot_number": "L-002", "quantity": 2.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        nov = res["novedades"]
        self.assertEqual(nov[str(env["product"].id)]["motivos"], ["TIPO"])
        self.assertEqual(nov[str(otro.id)]["motivos"], ["TIPO"])
        self.assertEqual(nov[str(env["product"].id)]["name"], "Tomate")

    def test_tipo_mas_limite_en_el_mismo_producto(self):
        env = self._seed_env(
            stock=100.0, waste_limit=20.0,
            waste_type=WasteType(name="Cadena de frio", code="TEMPERATURA",
                                 severity="CRITICA", requires_approval=True,
                                 applies_central=False, is_active=True))
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001",
             "quantity": 30.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PENDIENTE")
        nov = res["novedades"]
        self.assertIn("TIPO", nov[str(env["product"].id)]["motivos"])
        self.assertIn("LIMITE", nov[str(env["product"].id)]["motivos"])
        self.assertEqual(nov[str(env["product"].id)]["name"], "Tomate")

    def test_vencido_motivo_informativo_en_merma_aprobada(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001",
             "quantity": 5.0},
        ])
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APROBADO")
        nov = res["novedades"]
        self.assertEqual(nov[str(env["product"].id)]["motivos"], ["VENCIDO"])

    def test_motivos_quedan_en_audit_de_creacion(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        res = self._register(env, [
            {"product_id": env["product"].id, "lot_number": "L-001",
             "quantity": 30.0}
        ])
        self.assertEqual(res["status"], "PENDIENTE")
        audit = AuditLog.query.filter_by(
            affected_table="waste", action="MERMA"
        ).order_by(AuditLog.id.desc()).first()
        self.assertIsNotNone(audit)
        data = audit.changed_data
        if isinstance(data, str):
            import json
            data = json.loads(data)
        self.assertEqual(data["motivos"], {str(env["product"].id): ["VENCIDO", "LIMITE"]})
        self.assertTrue(data["requiere_aprobacion"])

    # ------------------------------------------------------------------
    # 8.11) DEEP-LINK: /waste/merma/new?type=VENCIDO (audio 9)
    # ------------------------------------------------------------------
    def test_deep_link_type_vencido_no_bloquea_nada(self):
        env = self._seed_central_env(code="VENCIDO")
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        # El tipo ya no es parte de la cabecera: el ?type= es inocuo.
        resp = client.get("/waste/merma/new?type=VENCIDO")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("locked_type_code", resp.get_data(as_text=True))

    def test_deep_link_tipo_inexistente_no_bloquea_nada(self):
        env = self._seed_central_env(code="VENCIDO")
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.get("/waste/merma/new?type=NOEXISTE")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("locked_type_code", resp.get_data(as_text=True))

    # ------------------------------------------------------------------
    # 8.12) ALERTA DE VENCIDOS (P4 / audio 9): detección y banner
    # ------------------------------------------------------------------
    def test_get_expired_lots_detecta_lote_vencido_con_saldo(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        vencidos = RegisterWasteRepository.get_expired_lots(env["location_id"])
        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0]["lot_number"], "L-001")
        self.assertEqual(vencidos[0]["product_name"], "Tomate")
        self.assertEqual(vencidos[0]["quantity"], 50.0)

    def test_get_expired_lots_ignora_lote_vigente(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0,
                             lot_expiration=date.today() + timedelta(days=30))
        self.assertEqual(RegisterWasteRepository.get_expired_lots(env["location_id"]), [])

    def test_get_expired_lots_central_detecta_vencido(self):
        env = self._seed_central_env(stock=100.0, waste_limit=20.0, lot_qty=100.0)
        vencidos = RegisterWasteRepository.get_expired_lots(1)
        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0]["lot_number"], env["lot"])
        self.assertEqual(vencidos[0]["quantity"], 100.0)

    def test_renderizar_registro_muestra_banner_de_vencidos(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(env["user_id"])
        resp = client.get("/waste/merma/new")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Productos vencidos detectados", html)
        self.assertIn("L-001", html)
        self.assertIn("/waste/merma/new", html)
        self.assertIn("Registrar merma de vencido", html)

    # ------------------------------------------------------------------
    # 8.12) REGLA DE TIEMPO: solo cuentan mermas decisivas (historial)
    # ------------------------------------------------------------------
    def test_ultima_merma_rechazada_no_cuenta_como_ultima(self):
        env = self._seed_env(stock=100.0, waste_limit=20.0)
        u_id = env["user_id"]
        aprobada = Waste(location_id=env["location_id"],
                         waste_type_id=env["waste_type"].id,
                         user_id=u_id, status="APROBADO",
                         date=datetime.utcnow() - timedelta(days=20),
                         total_quantity=5.0, total_cost=0, currency="USD")
        rechazada = Waste(location_id=env["location_id"],
                          waste_type_id=env["waste_type"].id,
                          user_id=u_id, status="RECHAZADO",
                          date=datetime.utcnow() - timedelta(days=1),
                          total_quantity=5.0, total_cost=0, currency="USD")
        db.session.add_all([aprobada, rechazada])
        db.session.commit()
        data = RegisterWasteRepository.get_time_rule_data(env["location_id"])
        self.assertGreaterEqual(data["days_since_last"], 19)
        self.assertLessEqual(data["days_since_last"], 22)

    # ------------------------------------------------------------------
    # 10) IDEMPOTENCIA (request_id)
    # ------------------------------------------------------------------
    def test_request_id_duplicado_no_crea_doble_merma(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        items = [{"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0,
                  "waste_type_id": env["waste_type"].id}]

        res1 = register_waste(
            user_id=env["user_id"],
            location_id=env["location_id"],
            items=items,
            notes="Prueba idempotencia",
            request_id="req-abc-123",
        )
        self.assertTrue(res1["success"])
        self.assertEqual(res1["status"], "APROBADO")

        res2 = register_waste(
            user_id=env["user_id"],
            location_id=env["location_id"],
            items=items,
            notes="Prueba idempotencia",
            request_id="req-abc-123",
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2.get("duplicate"))
        self.assertEqual(res2["waste_id"], res1["waste_id"])

        db.session.expunge_all()
        self.assertEqual(
            Waste.query.filter_by(request_id="req-abc-123").count(), 1
        )
        inv = Inventory.query.filter_by(
            product_id=env["product_id"], location_id=env["location_id"]
        ).first()
        # El stock se desconta UNA sola vez (45.0), no 2 veces.
        self.assertEqual(float(inv.current_quantity), 45.0)
        self.assertEqual(
            AuditLog.query.filter_by(affected_table="inventory", action="MERMA").count(), 1
        )

    def test_request_id_distinto_si_crea_nueva_merma(self):
        env = self._seed_env(stock=50.0, waste_limit=20.0)
        items = [{"product_id": env["product"].id, "lot_number": "L-001", "quantity": 5.0,
                  "waste_type_id": env["waste_type"].id}]
        res1 = register_waste(
            user_id=env["user_id"], location_id=env["location_id"],
            items=items,
            notes="Prueba 1", request_id="req-uno",
        )
        res2 = register_waste(
            user_id=env["user_id"], location_id=env["location_id"],
            items=items,
            notes="Prueba 2", request_id="req-dos",
        )
        self.assertTrue(res1["success"])
        self.assertTrue(res2["success"])
        self.assertNotEqual(res1["waste_id"], res2["waste_id"])
        self.assertFalse(res2.get("duplicate"))

    # ------------------------------------------------------------------
    # 11) CONSUMO SIN LOTE ('N/A') — se descuenta FIFO sobre los lotes
    # ------------------------------------------------------------------
    def _seed_second_lot(self, env, lot_number, quantity, expiration):
        mov = Movement(
            type="TRASLADO",
            origin_location_id=env["origin"].id,
            destination_location_id=env["location_id"],
            status="COMPLETED",
            user_id=env["user_id"],
        )
        db.session.add(mov)
        db.session.flush()
        detail = MovementDetail(
            movement_id=mov.id,
            product_id=env["product_id"],
            lot_number=lot_number,
            quantity=quantity,
            received_quantity=quantity,
            missing_quantity=0.00,
            expiration_date=expiration,
        )
        db.session.add(detail)
        db.session.commit()

    def test_consumo_sin_lote_se_descuenta_primero_del_lote_mas_vencido(self):
        env = self._seed_env(stock=10.0, waste_limit=100.0)
        self._seed_second_lot(env, "L-002", 10.0, date.today() + timedelta(days=60))

        db.session.add(AuditLog(
            affected_table="inventory",
            action="GASTO_COCINA",
            severity="NORMAL",
            user_id=env["user_id"],
            location_id=env["location_id"],
            timestamp=datetime.utcnow(),
            changed_data={
                "product_id": env["product_id"],
                "product_name": "Tomate",
                "lot_number": "N/A",
                "previous_quantity": 20.0,
                "new_quantity": 16.0,
                "quantity_changed": -4.0,
                "notes": "Consumo sin lote",
            },
        ))
        db.session.commit()

        lots = RegisterWasteRepository.get_product_lots(
            env["product_id"], env["location_id"]
        )
        by_lot = {lot["lot_number"]: lot["quantity"] for lot in lots}
        # FIFO: el consumo sin lote descuenta primero del lote más viejo (L-001).
        self.assertEqual(by_lot.get("L-001"), 6.0)
        self.assertEqual(by_lot.get("L-002"), 10.0)

        vencidos = RegisterWasteRepository.get_expired_lots(env["location_id"])
        vencido = next((v for v in vencidos if v["product_id"] == env["product_id"]), None)
        self.assertIsNotNone(vencido)
        self.assertEqual(vencido["lot_number"], "L-001")
        self.assertEqual(vencido["quantity"], 6.0)


if __name__ == "__main__":
    unittest.main()