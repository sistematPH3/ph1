# =============================================================================
# PRUEBA DE LA BANDEJA DE RESPUESTAS DEL ADMINISTRADOR
# -----------------------------------------------------------------------------
# Qué verifica:
#   1) Un traslado resuelto por el admin (auditoría RESOLUCION_DISPUTA) SÍ
#      aparece en la bandeja de respuestas.
#   2) Un traslado aún pendiente de arbitraje NO aparece.
#   3) El filtro por sedes funciona: un usuario que no participa del traslado
#      no ve la respuesta.
#   4) El resumen JSON (campana) devuelve la respuesta con sus datos.
#
# Para ejecutarla, en la carpeta ph1:
#   .\.venv\Scripts\python.exe -m unittest tests/logistics/test_response_inbox.py -v
# =============================================================================

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

from app import create_app, db
from app.models import (AuditLog, Location, Movement, MovementDetail,
                        Notification, Product, Role, User)
from app.logistics.repositories.response_inbox_repository import ResponseInboxRepository
from app.logistics.services.response_inbox_service import ResponseInboxService
from app.logistics.services.movement_dispute_service import _notify_response_resolved


class ResponseInboxTest(unittest.TestCase):

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

    # =========================================================================
    # AYUDA: sede(s), producto, usuario de un rol y traslado.
    # =========================================================================
    def _make_location(self, name):
        loc = Location(name=name, state="Caracas")
        db.session.add(loc)
        db.session.flush()
        return loc

    def _make_user(self, email, role_name, locations=None):
        role = Role(name=role_name)
        db.session.add(role)
        db.session.flush()
        user = User(name="U " + email, email=email, password_hash="x",
                    role_id=role.id)
        db.session.add(user)
        db.session.flush()
        if locations:
            user.locations = locations
            db.session.flush()
        return user

    def _make_movement(self, origin, dest, status, user):
        prod = Product(name="Tomate", sku="TOM-%d" % origin.id)
        db.session.add(prod)
        db.session.flush()
        mov = Movement(type="TRASLADO", origin_location_id=origin.id,
                       destination_location_id=dest.id, status=status,
                       user_id=user.id)
        db.session.add(mov)
        db.session.flush()
        db.session.add(MovementDetail(movement_id=mov.id, product_id=prod.id,
                                      lot_number="L-001", quantity=10,
                                      received_quantity=8,
                                      missing_quantity=2))
        db.session.flush()
        return mov

    def _report_novedad(self, mov, receiver, novelty_type, items=None):
        """Reproduce lo que hace movement_reception_service: la auditoría de
        recepción que registra la clasificación original de la novedad."""
        detail = mov.details[0]
        db.session.add(AuditLog(
            affected_table='movements',
            action='RECEPCION_NOVEDAD',
            severity='ALERTA',
            user_id=receiver.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RECEPCION_NOVEDAD",
                "novelty_type": novelty_type,
                "items": items or [
                    {
                        "detail_id": detail.id,
                        "product_id": detail.product_id,
                        "sku": "TOM-1",
                        "product_name": "Tomate",
                        "lot_number": detail.lot_number,
                        "dispatched_qty": 10.0,
                        "received_qty": 8.0,
                        "missing_qty": 2.0,
                        "item_condition": "CONFORME",
                        "specific_novelty": "FALTANTE",
                    }
                ],
                "notes": "Se reporta el faltante.",
                "received_by_user_id": receiver.id,
            }
        ))
        db.session.commit()

    def _notify(self, user, mov, read=False):
        """Crea la Notification RESPUESTA_TRASLADO que el receptor recibe en
        el servidor (igual que hace resolve_dispute al emitir el dictamen)."""
        db.session.add(Notification(
            user_id=user.id,
            location_id=mov.destination_location_id,
            type='RESPUESTA_TRASLADO',
            message=f"Respuesta del Administrador · Traslado #{mov.id}",
            is_read=read,
            movement_id=mov.id,
        ))
        db.session.commit()

    def _resolve(self, mov, admin, notes="Dictamen: se queda la mercancía."):
        mov.status = "COMPLETADO"
        mov.resolution_notes = notes
        mov.resolved_by_id = admin.id
        db.session.add(AuditLog(
            affected_table='movements',
            action='RESOLUCION_DISPUTA',
            severity='NORMAL',
            user_id=admin.id,
            changed_data={
                "movement_id": mov.id,
                "event": "RESOLUCION_DISPUTA",
                "general_notes": notes,
                "items": [
                    {
                        "detail_id": mov.details[0].id,
                        "product_id": mov.details[0].product_id,
                        "lot_number": mov.details[0].lot_number,
                        "action": "ACEPTAR_RECEPCION",
                        "credited_qty": 8.0,
                        "return_qty": 0.0,
                        "lost_qty": 2.0,
                    }
                ],
                "resolution_summary": {
                    "credited_total": 8.0,
                    "returned_total": 0.0,
                    "lost_total": 2.0,
                },
                "linked_return_movement_id": None,
                "user_id": admin.id,
                "timestamp": "2026-08-30T12:00:00Z",
            }
        ))
        db.session.commit()

    # =========================================================================
    # CASO 1: traslado resuelto aparece en la bandeja para el admin.
    # =========================================================================
    def test_traslado_resuelto_aparece_en_bandeja(self):
        origin = self._make_location("Sede Origen")
        dest = self._make_location("Sede Destino")
        admin = self._make_user("admin@test.com", "Administrator")
        user = self._make_user("receptor@test.com", "Operations", locations=[dest])

        mov = self._make_movement(origin, dest, "FALTANTE_CONTEO", user)
        self._report_novedad(mov, user, "FALTANTE_CONTEO")
        self._resolve(mov, admin, notes="Dictamen administrativo final")
        # El receptor recibe la notificación en el servidor (leído en BD).
        self._notify(user, mov)

        resp_admin = ResponseInboxRepository.get_admin_responses(admin)
        resp_receptor = ResponseInboxRepository.get_admin_responses(user)

        self.assertEqual(len(resp_admin), 1)
        mov_resp = resp_admin[0]
        self.assertEqual(mov_resp.id, mov.id)
        self.assertEqual(mov_resp.resolution_notes, "Dictamen administrativo final")
        self.assertEqual(mov_resp.response_by.name, "U admin@test.com")

        # Información que identifica al traslado en la bandeja:
        #  - Clasificación original de la novedad (recuperada de la recepción).
        self.assertEqual(mov_resp.novedad_type, "FALTANTE_CONTEO")
        self.assertEqual(mov_resp.novedad_label, "Faltante de Conteo")
        #  - Quién reportó.
        self.assertEqual(mov_resp.reported_by.name, "U receptor@test.com")
        #  - Detalle de lo recibido por producto.
        self.assertEqual(len(mov_resp.novedad_items), 1)
        self.assertEqual(mov_resp.novedad_items[0]["product_name"], "Tomate")
        self.assertEqual(mov_resp.novedad_items[0]["specific_novelty"], "Faltante")
        #  - Síntesis del veredicto (acreditado / devuelto / perdido).
        self.assertEqual(mov_resp.resolution_summary["credited_total"], 8.0)
        self.assertEqual(mov_resp.resolution_summary["lost_total"], 2.0)
        #  - Decisiones administrativas por producto.
        self.assertEqual(len(mov_resp.resolution_items), 1)
        self.assertEqual(mov_resp.resolution_items[0]["action_label"], "Aceptar recepción")
        self.assertEqual(mov_resp.resolution_items[0]["product"].name, "Tomate")

        # El receptor de la sede destino también la ve, y la ve como NO leída
        # (el estado de lectura vive en el servidor).
        self.assertEqual(len(resp_receptor), 1)
        self.assertEqual(resp_receptor[0].id, mov.id)
        self.assertFalse(resp_receptor[0].is_read)

        # Marcar como leída baja el contador del servidor.
        self.assertEqual(ResponseInboxRepository.get_unread_count(user), 1)
        ResponseInboxService.mark_as_read(user, mov.id)
        self.assertEqual(ResponseInboxRepository.get_unread_count(user), 0)
        resp_receptor2 = ResponseInboxRepository.get_admin_responses(user)
        self.assertTrue(resp_receptor2[0].is_read)

    # =========================================================================
    # CASO 2: traslado pendiente (sin respuesta) NO aparece en la bandeja.
    # =========================================================================
    def test_traslado_pendiente_no_aparece(self):
        origin = self._make_location("Sede Origen")
        dest = self._make_location("Sede Destino")
        admin = self._make_user("admin@test.com", "Administrator")
        user = self._make_user("receptor@test.com", "Operations", locations=[dest])

        self._make_movement(origin, dest, "SOBRANTE_EXCEDENTE", user)

        resp = ResponseInboxRepository.get_admin_responses(admin)
        self.assertEqual(resp, [])

    # =========================================================================
    # CASO 3: usuario de OTRA sede no ve la respuesta (filtro por sedes).
    # =========================================================================
    def test_filtro_por_sedes(self):
        origin = self._make_location("Sede Origen")
        dest = self._make_location("Sede Destino")
        otra_sede = self._make_location("Sede Lejana")
        admin = self._make_user("admin@test.com", "Administrator")
        receptor = self._make_user("receptor@test.com", "Operations", locations=[dest])
        intrometido = self._make_user("otro@test.com", "Operations", locations=[otra_sede])

        mov = self._make_movement(origin, dest, "FALTANTE_CONTEO", receptor)
        self._resolve(mov, admin)
        self._notify(receptor, mov)

        resp_intro = ResponseInboxRepository.get_admin_responses(intrometido)
        self.assertEqual(resp_intro, [])

        # El receptor (sede destino, notificado) sí la ve; el de otra sede no.
        resp_receptor = ResponseInboxRepository.get_admin_responses(receptor)
        self.assertEqual(len(resp_receptor), 1)

    # =========================================================================
    # CASO 4: el resumen JSON de la campana devuelve la respuesta.
    # =========================================================================
    def test_resumen_de_la_campana(self):
        origin = self._make_location("Sede Origen")
        dest = self._make_location("Sede Destino")
        admin = self._make_user("admin@test.com", "Administrator")
        receptor = self._make_user("receptor@test.com", "Operations", locations=[dest])

        mov = self._make_movement(origin, dest, "FALTANTE_CONTEO", receptor)
        self._report_novedad(mov, receptor, "FALTANTE_CONTEO")
        self._resolve(mov, admin, notes="Se acredita la entrada.")
        self._notify(receptor, mov)

        summary = ResponseInboxService.get_inbox_summary(receptor)

        # El número de pendientes lo calcula el SERVIDOR, no el navegador.
        self.assertEqual(summary["unread_count"], 1)
        self.assertEqual(summary["total"], 1)
        item = summary["items"][0]
        self.assertEqual(item["id"], mov.id)
        self.assertFalse(item["is_read"])
        self.assertEqual(item["origin"], origin.name)
        self.assertEqual(item["destination"], dest.name)
        # La campana también recibe la información que identifica el traslado.
        self.assertEqual(item["novedad"], "Faltante de Conteo")
        self.assertEqual(item["product_count"], 1)
        self.assertEqual(item["products"][0]["product_name"], "Tomate")
        self.assertEqual(item["resolution_totals"]["credited"], 8.0)
        self.assertEqual(item["resolution_totals"]["lost"], 2.0)
        self.assertEqual(item["reported_by"], "U receptor@test.com")
        self.assertEqual(item["notes"], "Se acredita la entrada.")
        self.assertEqual(item["resolved_by"], "U admin@test.com")
        self.assertIsNotNone(item["resolution_date"])

        # Tras marcar leído en el servidor, el contador baja.
        ResponseInboxService.mark_as_read(receptor, mov.id)
        summary2 = ResponseInboxService.get_inbox_summary(receptor)
        self.assertEqual(summary2["unread_count"], 0)
        self.assertTrue(summary2["items"][0]["is_read"])

    # =========================================================================
    # CASO 5: al resolver, se crea una Notification por destinatario en el
    # servidor (receptor + todos los admin/finanzas, incluido quien emite el
    # dictamen: los admins lo ven TODO, aunque la hayan resuelto ellos).
    # =========================================================================
    def test_notify_resolve_crea_notificaciones(self):
        origin = self._make_location("Sede Origen")
        dest = self._make_location("Sede Destino")
        admin = self._make_user("admin@test.com", "Administrator")
        receptor = self._make_user("receptor@test.com", "Operations", locations=[dest])
        otro_admin = self._make_user("admin2@test.com", "Administrator")

        mov = self._make_movement(origin, dest, "FALTANTE_CONTEO", receptor)

        _notify_response_resolved(mov, resolver_user_id=admin.id)

        nots = Notification.query.filter_by(type='RESPUESTA_TRASLADO',
                                            movement_id=mov.id).all()
        self.assertEqual(len(nots), 3)  # receptor + otro_admin + admin
        notify_ids = [n.user_id for n in nots]
        self.assertIn(receptor.id, notify_ids)
        self.assertIn(otro_admin.id, notify_ids)
        self.assertIn(admin.id, notify_ids)
        self.assertFalse(all(n.is_read for n in nots))

        # Idempotente: volver a llamar no duplica notificaciones.
        _notify_response_resolved(mov, resolver_user_id=admin.id)
        self.assertEqual(
            Notification.query.filter_by(type='RESPUESTA_TRASLADO',
                                         movement_id=mov.id).count(),
            3
        )


if __name__ == "__main__":
    unittest.main()