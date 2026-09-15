from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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
    def test_duration_wording_preserves_exact_plan_values(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        cases = [
            (40, 55, "entre 40 y 55 minutos", True),
            (40, 55, "de 40 a 55 minutos", True),
            (40, 55, "40–55 min", True),
            (35, 35, "35 minutos", True),
            (35, 35, "35 a 35 minutos", True),
            (40, 55, "40 minutos", False),
            (40, 55, "entre 40 y 50 minutos", False),
            (35, 35, "135 minutos", False),
            (35, 35, "25–35 minutos", False),
            (35, 35, "35 a 40 minutos", False),
            (35, 35, "35,5 minutos", False),
        ]
        for low, high, wording, accepted in cases:
            with self.subTest(wording=wording):
                session = {"date": tomorrow.isoformat(), "duration_min": low,
                           "duration_max": high, "session_type": "easy"}
                compact = compact_context({})
                compact["extra_context"]["question_target"] = {
                    "kind": "tomorrow", "date": tomorrow.isoformat(),
                    "sessions": [session],
                }
                response = response_with(
                    answer=f"El plan de mañana incluye {wording} de rodaje fácil.",
                    decisions=[{"action": "keep_plan", "reason": "Sesión del plan vigente.",
                                "date": tomorrow.isoformat(), "session_type": "easy",
                                "duration_min": low, "duration_max_min": high}],
                )
                if accepted:
                    validate_coach_decisions(response, compact)
                else:
                    with self.assertRaisesRegex(ValueError, "duration range"):
                        validate_coach_decisions(response, compact)

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

    def test_contract_rejects_an_intensity_label_as_target_pace(self) -> None:
        with self.assertRaises(ValidationError):
            response_with(
                decisions=[
                    {
                        "action": "keep_plan",
                        "reason": "El plan vigente sigue siendo adecuado.",
                        "target_pace": "easy",
                    }
                ]
            )

    def test_contract_preserves_a_duration_range(self) -> None:
        response = response_with(
            decisions=[
                {
                    "action": "keep_plan",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "duration_min": 40,
                    "duration_max_min": 55,
                }
            ]
        )

        self.assertEqual(response.decisions[0].duration_min, 40)
        self.assertEqual(response.decisions[0].duration_max_min, 55)

    def test_contract_rejects_an_inverted_duration_range(self) -> None:
        with self.assertRaises(ValidationError):
            response_with(
                decisions=[
                    {
                        "action": "keep_plan",
                        "reason": "El plan vigente sigue siendo adecuado.",
                        "duration_min": 55,
                        "duration_max_min": 40,
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

    def test_context_normalizes_an_intensity_label_as_no_target_pace(self) -> None:
        compact = compact_context(
            {
                "training_plan": {
                    "sessions": [
                        {
                            "date": "2026-09-16",
                            "sport": "running",
                            "intensity": "easy",
                            "target_pace": "easy",
                        }
                    ]
                }
            }
        )

        session = compact["extra_context"]["training_plan"]["sessions"][0]
        self.assertIsNone(session["target_pace"])
        self.assertEqual(session["intensity"], "easy")

    def test_tomorrow_decision_must_match_the_planned_session(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [
                {
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "duration_min": 40,
                    "duration_max": 55,
                    "intensity": "easy",
                }
            ],
        }
        response = response_with(
            answer="Mañana toca un rodaje fácil de 40 a 55 minutos, según el plan vigente.",
            decisions=[
                {
                    "action": "keep_plan",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "intensity": "easy",
                    "duration_min": 40,
                    "duration_max_min": 55,
                }
            ],
        )

        validate_coach_decisions(response, compact)

    def test_tomorrow_decision_rejects_a_missing_date_or_duration_range(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [
                {
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "duration_min": 40,
                    "duration_max": 55,
                    "intensity": "easy",
                }
            ],
        }
        response = response_with(
            answer="Mañana toca un rodaje fácil de 40 a 55 minutos, según el plan vigente.",
            decisions=[
                {
                    "action": "modify_session",
                    "reason": "La recuperación no es completa y la carga ha subido.",
                    "sport": "running",
                    "session_type": "running",
                }
            ],
        )

        with self.assertRaisesRegex(ValueError, "target date"):
            validate_coach_decisions(response, compact)

    def test_tomorrow_decision_requires_target_date_without_a_planned_session(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [],
        }
        response = response_with(
            answer="Mañana necesito confirmar qué sesión tienes planificada antes de recomendarla.",
            decisions=[
                {
                    "action": "ask_user",
                    "reason": "No hay una sesión planificada disponible.",
                }
            ],
        )

        with self.assertRaisesRegex(ValueError, "target date"):
            validate_coach_decisions(response, compact)

    def test_tomorrow_answer_must_state_the_validated_duration_range(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [
                {
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "duration_min": 40,
                    "duration_max": 55,
                    "intensity": "easy",
                }
            ],
        }
        response = response_with(
            answer="Mañana toca un rodaje fácil de 30 minutos, según el plan vigente.",
            decisions=[
                {
                    "action": "keep_plan",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "intensity": "easy",
                    "duration_min": 40,
                    "duration_max_min": 55,
                }
            ],
        )

        with self.assertRaisesRegex(ValueError, "duration range"):
            validate_coach_decisions(response, compact)

    def test_tomorrow_decision_cannot_label_an_unchanged_plan_as_modified(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [
                {
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "duration_min": 40,
                    "duration_max": 55,
                    "intensity": "easy",
                }
            ],
        }
        response = response_with(
            answer="Mañana toca un rodaje fácil de 40 a 55 minutos, según el plan vigente.",
            decisions=[
                {
                    "action": "modify_session",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "intensity": "easy",
                    "duration_min": 40,
                    "duration_max_min": 55,
                }
            ],
        )

        with self.assertRaisesRegex(ValueError, "modify_session"):
            validate_coach_decisions(response, compact)

    def test_tomorrow_validates_every_planned_session(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        compact = compact_context({})
        compact["extra_context"]["question_target"] = {
            "kind": "tomorrow",
            "date": tomorrow.isoformat(),
            "sessions": [
                {
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "duration_min": 40,
                    "duration_max": 55,
                    "intensity": "easy",
                },
                {
                    "date": tomorrow.isoformat(),
                    "sport": "strength",
                    "session_type": "full_body",
                    "duration_min": 35,
                    "duration_max": 40,
                    "intensity": "moderate",
                },
            ],
        }
        response = response_with(
            answer=(
                "Mañana toca un rodaje fácil de 40 a 55 minutos y una sesión "
                "full body de 35 a 40 minutos, según el plan vigente."
            ),
            decisions=[
                {
                    "action": "keep_plan",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "date": tomorrow.isoformat(),
                    "sport": "running",
                    "session_type": "easy_run",
                    "intensity": "easy",
                    "duration_min": 40,
                    "duration_max_min": 55,
                },
                {
                    "action": "keep_plan",
                    "reason": "El plan vigente sigue siendo adecuado.",
                    "date": tomorrow.isoformat(),
                    "sport": "strength",
                    "session_type": "full_body",
                    "intensity": "moderate",
                    "duration_min": 35,
                    "duration_max_min": 40,
                },
            ],
        )

        validate_coach_decisions(response, compact)
