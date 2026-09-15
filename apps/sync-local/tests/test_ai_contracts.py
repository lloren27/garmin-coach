from __future__ import annotations

import unittest
from datetime import date, timedelta

from pydantic import ValidationError

from garmin_sync.ai_contracts import CoachStructuredResponse
from garmin_sync.ai_worker import compact_context, validate_coach_decisions


def response_with(**overrides: object) -> CoachStructuredResponse:
    payload = {
        "response_type": "single_session",
        "answer": "Hoy descansa y revisa mañana cómo responde tu recuperación.",
        "decisions": [],
        "evidence": [],
        "warnings": [],
        "missing_data": [],
    }
    payload.update(overrides)
    return CoachStructuredResponse.model_validate(payload)


class CoachContractsTests(unittest.TestCase):
    def test_contract_rejects_unknown_fields_actions_and_negative_duration(self) -> None:
        for decision in (
            {"action": "invented", "reason": "No es una acción permitida."},
            {"action": "rest", "reason": "Necesitas recuperación suficiente.", "duration_min": -20},
            {"action": "rest", "reason": "Necesitas recuperación suficiente.", "unknown": "value"},
        ):
            with self.subTest(decision=decision):
                with self.assertRaises(ValidationError):
                    response_with(decisions=[decision])

    def test_contract_rejects_rest_with_training_targets(self) -> None:
        with self.assertRaises(ValidationError):
            response_with(
                decisions=[
                    {
                        "action": "rest",
                        "reason": "Necesitas recuperación suficiente.",
                        "target_power_w": 210,
                    }
                ]
            )

    def test_domain_validation_rejects_past_dates(self) -> None:
        response = response_with(
            decisions=[
                {
                    "action": "recovery",
                    "reason": "Mantén una carga muy suave hoy.",
                    "date": (date.today() - timedelta(days=1)).isoformat(),
                }
            ]
        )

        with self.assertRaises(ValueError):
            validate_coach_decisions(response, compact_context({}))

    def test_domain_validation_rejects_evidence_from_absent_source(self) -> None:
        response = response_with(
            evidence=[
                {
                    "source": "wattwise",
                    "fact": "La potencia media fue estable.",
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "wattwise"):
            validate_coach_decisions(response, compact_context({}))

    def test_domain_validation_accepts_evidence_from_available_source(self) -> None:
        response = response_with(
            evidence=[
                {
                    "source": "wattwise",
                    "fact": "La potencia media fue estable.",
                }
            ]
        )

        validate_coach_decisions(
            response,
            compact_context({"wattwise": {"received_at": "2026-09-15"}}),
        )
