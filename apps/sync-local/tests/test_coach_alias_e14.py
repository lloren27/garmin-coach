import json
import copy
import unittest
from datetime import date, datetime
from pathlib import Path

from garmin_sync.coach_intent import resolve_intent
from garmin_sync.coach_deterministic import deterministic_response
from garmin_sync.coach_generation_context import build_snapshot


CASES_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "coach_alias_e14_cases.json"
with CASES_PATH.open(encoding="utf-8") as handle:
    CASES = json.load(handle)


def normalized_time_context(context):
    """Model records rewritten by the next full worker synchronization."""
    from zoneinfo import ZoneInfo
    for row in context.get('extra_context', {}).get('recent_activities', []):
        row.setdefault('local_date', row.get('date'))
        row.setdefault('time_context', 'Europe/Madrid')
        value = row.get('started_at')
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                continue
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                row.setdefault('started_at_utc', parsed.astimezone(ZoneInfo('UTC')).isoformat())
    return context


class CoachAliasWorkerE14Tests(unittest.TestCase):
    now = datetime.fromisoformat(CASES["now"])

    def assert_resolution(self, case):
        result = resolve_intent(case["question"], now=self.now)
        self.assertEqual(result.primary_intent.value, case["expected_intent"])
        self.assertEqual(result.selector.value, case["expected_selector"])
        expected_dates = tuple(date.fromisoformat(value) for value in case.get("expected_observed_dates", []))
        self.assertEqual(result.observed_dates, expected_dates)
        expected_advice_dates = tuple(date.fromisoformat(value) for value in case.get("expected_advice_dates", []))
        self.assertEqual(result.advice_dates, expected_advice_dates)
        expected_clarification = case.get("expected_clarification")
        actual = result.components[0].clarification_code
        self.assertEqual(actual.value if actual else None, expected_clarification)
        actual_sport = result.components[0].sport
        self.assertEqual(actual_sport.value if actual_sport else None, case.get("expected_sport"))
        actual_metric = result.components[0].metric
        self.assertEqual(actual_metric.value if actual_metric else None, case.get("expected_metric"))

    def test_shared_canonical_alias_phrases_are_activation_gates(self):
        for case in CASES["canonical_aliases"]:
            with self.subTest(alias=case["id"]):
                self.assert_resolution(case)

    def test_alias_arguments_are_preserved_and_worker_clarifies(self):
        for case in CASES["argument_cases"]:
            with self.subTest(case=case["id"]):
                self.assert_resolution(case)

    def test_human_paraphrases_are_diagnostic_not_activation_gates(self):
        for case in CASES["paraphrases"]:
            with self.subTest(case=case["id"]):
                self.assertFalse(case["activation_gate"])
                self.assert_resolution(case)

    def test_e14_paraphrase_answers_match_shared_expectations(self):
        project_root = Path(__file__).resolve().parents[3]
        phase3 = json.loads(
            (project_root / "docs/restructuring/fase3_evaluacion/v1/fixtures.json").read_text(encoding="utf-8")
        )
        context = phase3["base_fixtures"][CASES["coach_context_fixture"]]["estado_inicial"]
        for case in CASES["paraphrases"]:
            if "expected_e14_answer_contains" not in case:
                continue
            with self.subTest(case=case["id"]):
                response = deterministic_response(
                    case["question"], normalized_time_context(copy.deepcopy(context)), now=self.now
                )
                for fragment in case["expected_e14_answer_contains"]:
                    self.assertIn(fragment, response.answer)
                self.assertEqual(bool(response.evidence), case["expected_e14_has_evidence"])

    def test_shared_analysis_regressions_have_the_expected_intent_contract(self):
        for case in CASES["analysis_regressions"]:
            with self.subTest(case=case["id"]):
                self.assert_resolution(case)

    def test_incomparable_times_insufficient_data_and_unknown_plan_sport_are_explicit(self):
        from garmin_sync.coach_analysis import build_analysis_facts

        project_root = Path(__file__).resolve().parents[3]
        phase3 = json.loads(
            (project_root / "docs/restructuring/fase3_evaluacion/v1/fixtures.json").read_text(encoding="utf-8")
        )
        base = phase3["base_fixtures"][CASES["coach_context_fixture"]]["estado_inicial"]
        for case in CASES["analysis_regressions"]:
            def mutate(context, case_id=case["id"]):
                if case_id == "incomparable-activity-times":
                    context["recent_activities"] = [
                        {"id": "bike-madrid", "source": "garmin", "sport": "cycling",
                         "date": "2026-10-03", "local_date": "2026-10-03",
                         "started_at": "2026-10-03T08:00:00", "time_context": "Europe/Madrid",
                         "duration_s": 1800, "km": 8},
                        {"id": "bike-travel", "source": "strava", "sport": "cycling",
                         "date": "2026-10-03", "local_date": "2026-10-03",
                         "started_at": "2026-10-03T08:00:00", "time_context": "America/New_York",
                         "duration_s": 2400, "km": 10},
                    ]
                elif case_id == "insufficient-metric-data":
                    context["recent_activities"] = [{
                        "id": "run-no-max-hr", "source": "garmin", "sport": "running",
                        "date": "2026-10-03", "local_date": "2026-10-03",
                        "started_at_utc": "2026-10-03T07:00:00Z", "time_context": "Europe/Madrid",
                        "avg_hr": 141,
                    }]
                elif case_id == "plan-session-without-sport":
                    context["recent_activities"] = []
                    context["training_plan"]["sessions"] = [{
                        "id": "tomorrow-unknown-sport", "date": "2026-10-04", "status": "planned",
                        "duration_min": 60, "duration_max": 90,
                    }]

            data = copy.deepcopy(base)
            mutate(data["extra_context"])
            facts = build_analysis_facts(build_snapshot(case["question"], data, now=self.now))
            with self.subTest(case=case["id"]):
                self.assertIn(case["expected_limitation"], facts.limitations)

    def test_known_voice_transcript_and_typed_question_resolve_identically(self):
        for case in CASES["voice_parity"]:
            with self.subTest(case=case["id"]):
                typed = resolve_intent(case["typed_question"], now=self.now)
                transcribed = resolve_intent(case["transcript"], now=self.now)
                self.assertEqual(transcribed, typed)
                contract = {
                    "expected_intent": typed.primary_intent.value,
                    "expected_selector": typed.selector.value,
                    "expected_observed_dates": [value.isoformat() for value in typed.observed_dates],
                    "expected_sport": typed.components[0].sport.value if typed.components[0].sport else None,
                    "expected_metric": typed.components[0].metric.value if typed.components[0].metric else None,
                }
                for key, value in contract.items():
                    self.assertEqual(value, case[key])

    def test_canonical_aliases_produce_grounded_structured_analysis(self):
        project_root = Path(__file__).resolve().parents[3]
        phase3 = json.loads(
            (project_root / "docs/restructuring/fase3_evaluacion/v1/fixtures.json").read_text(encoding="utf-8")
        )
        context = phase3["base_fixtures"][CASES["coach_context_fixture"]]["estado_inicial"]
        for case in CASES["canonical_aliases"]:
            with self.subTest(alias=case["id"]):
                response = deterministic_response(
                    case["question"], normalized_time_context(copy.deepcopy(context)), now=self.now
                )
                self.assertIn("2026-10-03", response.answer)
                self.assertIn("1:45:04 registrados", response.answer)
                self.assertTrue(response.decisions)
                self.assertTrue(all(item.action == "ask_user" for item in response.decisions))
                self.assertIsNone(response.change_proposal)

    def test_day_aliases_keep_multisport_facts_separate_and_latest_activity_is_not_guessed(self):
        project_root = Path(__file__).resolve().parents[3]
        phase3 = json.loads(
            (project_root / "docs/restructuring/fase3_evaluacion/v1/fixtures.json").read_text(encoding="utf-8")
        )
        base = phase3["base_fixtures"][CASES["coach_context_fixture"]]["estado_inicial"]
        context = copy.deepcopy(base)
        context["extra_context"]["recent_activities"].append({
            "id": "synthetic-bike1", "source": "strava", "date": "2026-10-03",
            "started_at": "2026-10-03T16:00:00+02:00", "sport": "cycling",
            "km": 40.0, "duration_s": 5400, "avg_hr": 130, "max_hr": 155,
        })
        context["extra_context"]["training_plan"]["sessions"].append({
            "id": "synthetic-s2", "date": "2026-10-03", "status": "planned",
            "sport": "cycling", "session_type": "easy_ride", "intensity": "easy",
            "duration_min": 60, "duration_max": 90,
        })

        for question in (
            "Analiza mi entrenamiento de hoy.",
            "Analiza mi último día de entrenamiento.",
        ):
            with self.subTest(question=question):
                response = deterministic_response(question, copy.deepcopy(context), now=self.now)
                self.assertIn("cycling:", response.answer)
                self.assertIn("running:", response.answer)
                self.assertIn("no se suman TRIMP, TSS y carga muscular", response.answer)
                self.assertIn("correspondencia con el plan", response.answer)
                self.assertTrue(all(item.action == "ask_user" for item in response.decisions))
                self.assertIsNone(response.change_proposal)

        latest = deterministic_response(
            "Analiza mi última actividad.", copy.deepcopy(context), now=self.now
        )
        self.assertEqual(
            latest.answer,
            "No puedo ordenar esas actividades con fiabilidad. ¿Cuál quieres que analice?",
        )
        self.assertEqual(latest.evidence, [])
        self.assertTrue(all(item.action == "ask_user" for item in latest.decisions))
        self.assertIsNone(latest.change_proposal)

    def test_multisport_day_groups_metrics_and_asks_for_plan_once(self):
        project_root = Path(__file__).resolve().parents[3]
        phase3 = json.loads(
            (project_root / "docs/restructuring/fase3_evaluacion/v1/fixtures.json").read_text(encoding="utf-8")
        )
        context = copy.deepcopy(
            phase3["base_fixtures"][CASES["coach_context_fixture"]]["estado_inicial"]
        )
        extra = context["extra_context"]
        extra["training_plan"] = {"sessions": []}
        extra["recent_activities"].append({
            "id": "synthetic-strength",
            "source": "garmin",
            "date": "2026-10-03",
            "started_at": "2026-10-03T19:00:00+02:00",
            "sport": "strength",
            "duration_s": 4172,
        })

        response = deterministic_response(
            "Analiza mi entrenamiento de hoy.", context, now=self.now
        )

        self.assertIn("running: 1:45:04, 20,02 km (garmin, 2026-10-03)", response.answer)
        self.assertIn("strength: 1:09:32 (garmin, 2026-10-03)", response.answer)
        self.assertEqual(response.answer.count("¿Puedes aportar el plan para comparar estas actividades?"), 1)
        self.assertEqual(response.answer.count("No hay sesiones del plan compatibles"), 1)
        self.assertNotIn("running: 1:45:04 (garmin", response.answer)
        self.assertNotIn("running: 20,02 km (garmin", response.answer)


if __name__ == "__main__":
    unittest.main()
