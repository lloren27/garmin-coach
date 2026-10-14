import importlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CASES_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "coach_alias_e14_cases.json"
with CASES_PATH.open(encoding="utf-8") as handle:
    CASES = json.load(handle)


class CoachAliasAdapterE14Tests(unittest.TestCase):
    def setUp(self):
        try:
            self.adapter = importlib.import_module("app.coach_alias_adapter")
        except ModuleNotFoundError:
            self.adapter = None

    def test_canonical_alias_inputs_match_shared_contract(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        now = datetime.fromisoformat(CASES["now"])
        for case in CASES["canonical_aliases"]:
            with self.subTest(alias=case["id"]):
                result = self.adapter.adapt_coach_alias(case["input"], now=now)
                if not case["activation_gate"]:
                    self.assertIsNone(result)
                    continue
                self.assertEqual(result["question"], case["question"])
                self.assertEqual(result["scope"], case["scope"])

    def test_shared_regression_corpus_keeps_alias_gates_and_resolver_expectations_explicit(self):
        # The API owns alias adaptation; the worker owns natural-language resolution.
        # This suite checks the shared contract is present without copying the resolver.
        self.assertEqual(CASES["version"], 1)
        for case in CASES["paraphrases"] + CASES["analysis_regressions"]:
            with self.subTest(case=case["id"]):
                self.assertIn(case["expected_intent"], {
                    "analyze_activity", "analyze_day", "consult_plan", "recommend_next", "clarify"
                })
                self.assertIn(case["expected_selector"], {"by_date", "latest_activity", "latest_training_day"})
                if "expected_observed_dates" in case:
                    self.assertIsInstance(case["expected_observed_dates"], list)
                if "expected_advice_dates" in case:
                    self.assertIsInstance(case["expected_advice_dates"], list)
                self.assertFalse(case.get("activation_gate", False))
        for case in CASES["voice_parity"]:
            with self.subTest(voice_case=case["id"]):
                self.assertTrue(case["transcript"].strip())
                self.assertEqual(case["expected_intent"], "analyze_activity")
                self.assertEqual(case["expected_sport"], "running")
                self.assertEqual(case["expected_metric"], "max_hr")

    def test_argument_aliases_send_original_text_without_canonical_suffix(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        now = datetime.fromisoformat(CASES["now"])
        for case in CASES["argument_cases"]:
            with self.subTest(case=case["id"]):
                result = self.adapter.adapt_coach_alias(case["input"], now=now)
                if not case.get("alias_migrated", True):
                    self.assertIsNone(result)
                    continue
                self.assertEqual(result["question"], case["question"])
                self.assertEqual(result["scope"], "latest_available")

    def test_alias_normalization_and_allowlist(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        now = datetime.fromisoformat(CASES["now"])
        self.assertEqual(
            self.adapter.adapt_coach_alias("/HOY@coachbot", now=now)["question"],
            "Analiza mi entrenamiento de hoy.",
        )
        self.assertIsNone(self.adapter.adapt_coach_alias("/ultima", now=now))
        self.assertIsNone(self.adapter.adapt_coach_alias("/semana", now=now))

    def test_switch_parser_is_opt_in_and_rejects_invalid_values(self):
        self.assertFalse(self.adapter.parse_alias_routing_enabled(None))
        self.assertFalse(self.adapter.parse_alias_routing_enabled("off"))
        self.assertTrue(self.adapter.parse_alias_routing_enabled("TRUE"))
        self.assertIsNone(self.adapter.parse_alias_routing_enabled("yes please"))

    def test_route_switch_enqueues_only_allowlisted_aliases_with_v3_metadata(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        from app import main
        for enabled, expected_calls in (("0", 0), ("true", 1)):
            with self.subTest(enabled=enabled), patch.object(
                main, "settings", SimpleNamespace(coach_alias_routing_enabled=enabled)
            ), patch.object(main, "load_sync", return_value={}), patch.object(
                main, "load_profile", return_value={}
            ), patch.object(main, "create_ai_job", return_value={"id": "job"}) as create:
                main.route_message("/hoy", "user", "chat")
                self.assertEqual(create.call_count, expected_calls)
                if expected_calls:
                    self.assertEqual(create.call_args.kwargs["required_engine"], "v3")
                    self.assertEqual(create.call_args.kwargs["factual_scope"], "today")

    def test_retained_ultima_alias_stays_on_local_route_when_switch_is_on(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        from app import main
        with patch.object(
            main, "settings", SimpleNamespace(coach_alias_routing_enabled="true")
        ), patch.object(main, "load_sync", return_value={}), patch.object(
            main, "load_profile", return_value={}
        ), patch.object(main, "create_ai_job") as create:
            main.route_message("/ultima", "user", "chat")
        create.assert_not_called()

    def test_arguments_are_not_combined_with_canonical_question_at_route(self):
        self.assertIsNotNone(self.adapter, "app.coach_alias_adapter is not implemented")
        from app import main
        with patch.object(
            main, "settings", SimpleNamespace(coach_alias_routing_enabled="true")
        ), patch.object(main, "load_sync", return_value={}), patch.object(
            main, "load_profile", return_value={}
        ), patch.object(main, "create_ai_job", return_value={"id": "job"}) as create:
            main.route_message("/hoy ayer", "user", "chat")
        self.assertEqual(create.call_args.kwargs["text"], "/hoy ayer")
        self.assertEqual(create.call_args.kwargs["factual_scope"], "latest_available")


if __name__ == "__main__":
    unittest.main()
