"""Pruebas unitarias de las combinaciones cualitativas mixtas por renglón.

No requieren base de datos: validan el contrato compartido de las cuatro
duplas aprobadas y la matriz restrictiva de resoluciones del arbitraje.
"""

import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.logistics.requests.movement_dispute_validators import MovementDisputeValidator
from app.logistics.requests.qualitative_combination_validators import (
    get_allowed_actions,
    get_combination_label,
    is_allowed_combination,
)
from app.logistics.requests.movement_reception_validators import (
    validate_reception_payload,
)

HOY = date(2026, 11, 18)


def _detail(**overrides):
    base = dict(
        id=1,
        product_id=10,
        product_name="Tomate",
        lot_number="L-001",
        quantity=Decimal("10.00"),
        expiration_date=HOY + timedelta(days=30),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _payload(condition, secondary=None, **item_overrides):
    item = {
        "detail_id": 1,
        "received_quantity": 10,
        "item_condition": condition,
        "observed_physical_lot": None,
        "observed_physical_expiration": None,
        "secondary_item_condition": secondary,
    }
    item.update(item_overrides)
    return {
        "novelty_type": condition,
        "notes": "Inspección de muelle con evidencia fotográfica",
        "items": [item],
    }


class QualitativeCombinationsCatalogTest(unittest.TestCase):

    def test_las_cuatro_duplas_estan_aprobadas(self):
        duplas = [
            ("LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA"),
            ("VENCIMIENTO_PROXIMO", "INCIDENCIA_TEMPERATURA"),
            ("LOTE_NO_COINCIDE", "VIOLACION_CUSTODIA"),
            ("VENCIMIENTO_PROXIMO", "LOTE_NO_COINCIDE"),
        ]
        for primary, secondary in duplas:
            with self.subTest(primary=primary, secondary=secondary):
                self.assertTrue(is_allowed_combination(primary, secondary))
                self.assertTrue(is_allowed_combination(secondary, primary))
                self.assertIsNotNone(get_combination_label(primary, secondary))

    def test_una_dupla_no_aprobada_no_tiene_matriz(self):
        self.assertFalse(
            is_allowed_combination("INCIDENCIA_TEMPERATURA", "VIOLACION_CUSTODIA")
        )
        self.assertEqual(get_allowed_actions("INCIDENCIA_TEMPERATURA", "VIOLACION_CUSTODIA"), None)

    def test_la_accion_mas_restrictiva_va_primero(self):
        for primary, secondary in [
            ("LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA"),
            ("VENCIMIENTO_PROXIMO", "INCIDENCIA_TEMPERATURA"),
            ("LOTE_NO_COINCIDE", "VIOLACION_CUSTODIA"),
            ("VENCIMIENTO_PROXIMO", "LOTE_NO_COINCIDE"),
        ]:
            with self.subTest(primary=primary, secondary=secondary):
                self.assertEqual(get_allowed_actions(primary, secondary)[0], "RETORNO_EMERGENCIA")

    def test_corregir_lote_solo_se_permite_en_la_dupla_sin_riesgo_critico(self):
        permitidas = get_allowed_actions("VENCIMIENTO_PROXIMO", "LOTE_NO_COINCIDE")
        self.assertIn("CORREGIR_LOTE", permitidas)
        self.assertNotIn(
            "CORREGIR_LOTE",
            get_allowed_actions("LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA"),
        )
        self.assertNotIn(
            "CORREGIR_LOTE",
            get_allowed_actions("LOTE_NO_COINCIDE", "VIOLACION_CUSTODIA"),
        )


class DisputeCombinationActionTest(unittest.TestCase):

    def test_temperatura_mas_lote_no_permite_corregir_lote(self):
        ok, message = MovementDisputeValidator.validate_combination_action(
            "LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA", "CORREGIR_LOTE"
        )
        self.assertFalse(ok)
        self.assertIn("restrictiva", message)

    def test_temperatura_mas_lote_permite_retorno_y_merma(self):
        for action in ("RETORNO_EMERGENCIA", "DERIVAR_MERMA_SANITARIA"):
            with self.subTest(action=action):
                ok, message = MovementDisputeValidator.validate_combination_action(
                    "LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA", action
                )
                self.assertTrue(ok)
                self.assertIsNone(message)

    def test_sin_dupla_no_se_restringe(self):
        ok, message = MovementDisputeValidator.validate_combination_action(
            "LOTE_NO_COINCIDE", None, "CORREGIR_LOTE"
        )
        self.assertTrue(ok)
        self.assertIsNone(message)


class ReceptionCombinationValidationTest(unittest.TestCase):

    def _validate(self, payload, detail=None):
        details_map = {1: detail or _detail()}
        return validate_reception_payload(
            payload, details_map, umbral_vencimiento_dias=7, hoy=HOY
        )

    def test_acepta_lote_mas_temperatura(self):
        ok, result = self._validate(_payload(
            "LOTE_NO_COINCIDE", "INCIDENCIA_TEMPERATURA",
            observed_physical_lot="L-999",
        ))
        self.assertTrue(ok, result)
        self.assertEqual(result["items"][0]["secondary_item_condition"], "INCIDENCIA_TEMPERATURA")

    def test_acepta_vencimiento_mas_temperatura(self):
        ok, result = self._validate(_payload(
            "VENCIMIENTO_PROXIMO", "INCIDENCIA_TEMPERATURA",
            observed_physical_expiration=(HOY + timedelta(days=3)).isoformat(),
        ))
        self.assertTrue(ok, result)

    def test_acepta_lote_mas_custodia(self):
        ok, result = self._validate(_payload(
            "LOTE_NO_COINCIDE", "VIOLACION_CUSTODIA",
            observed_physical_lot="L-999",
        ))
        self.assertTrue(ok, result)

    def test_acepta_vencimiento_mas_lote(self):
        ok, result = self._validate(_payload(
            "VENCIMIENTO_PROXIMO", "LOTE_NO_COINCIDE",
            observed_physical_lot="L-999",
            observed_physical_expiration=(HOY + timedelta(days=3)).isoformat(),
        ))
        self.assertTrue(ok, result)

    def test_rechaza_dupla_no_aprobada(self):
        ok, errors = self._validate(_payload(
            "INCIDENCIA_TEMPERATURA", "VIOLACION_CUSTODIA",
            observed_physical_lot="L-999",
        ))
        self.assertFalse(ok)
        self.assertTrue(any("no está permitida" in str(e) for e in errors))

    def test_rechaza_secundaria_sobre_condicion_de_cantidad(self):
        ok, errors = self._validate(_payload(
            "FALTANTE_CONTEO", "LOTE_NO_COINCIDE",
            received_quantity=8,
            observed_physical_lot="L-999",
        ))
        self.assertFalse(ok)
        self.assertTrue(any("condición principal es de calidad" in str(e) for e in errors))

    def test_rechaza_secundaria_igual_a_la_principal(self):
        ok, errors = self._validate(_payload(
            "LOTE_NO_COINCIDE", "LOTE_NO_COINCIDE",
            observed_physical_lot="L-999",
        ))
        self.assertFalse(ok)
        self.assertTrue(any("distinta de la principal" in str(e) for e in errors))

    def test_dupla_con_lote_exige_lote_fisico(self):
        ok, errors = self._validate(_payload(
            "INCIDENCIA_TEMPERATURA", "LOTE_NO_COINCIDE",
        ))
        self.assertFalse(ok)
        self.assertTrue(any("lote impreso en el empaque" in str(e) for e in errors))

    def test_dupla_con_vencimiento_aplica_umbral(self):
        ok, errors = self._validate(_payload(
            "LOTE_NO_COINCIDE", "VENCIMIENTO_PROXIMO",
            observed_physical_lot="L-999",
            observed_physical_expiration=(HOY + timedelta(days=60)).isoformat(),
        ))
        self.assertFalse(ok)
        self.assertTrue(any("amplia vida útil" in str(e) for e in errors))


if __name__ == "__main__":
    unittest.main()
