from __future__ import annotations

import importlib
import json
import unittest
from datetime import datetime
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "late_response_cases.json"
)
with FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
    CASES = json.load(fixture_file)

try:
    response_timing = importlib.import_module("app.response_timing")
except ModuleNotFoundError:
    response_timing = None


class LateResponseTests(unittest.TestCase):
    def require_implementation(self):
        self.assertIsNotNone(
            response_timing,
            "app.response_timing must provide the late response contract",
        )

    def test_shared_fixture_cases_match_expected_classification(self):
        self.require_implementation()
        for case in CASES:
            with self.subTest(case=case["id"]):
                prefix = response_timing.late_response_prefix(
                    case.get("created_at"),
                    now=datetime.fromisoformat(case["now"]),
                )
                if case["expected"] == "on_time":
                    self.assertIsNone(prefix)
                elif case["expected"] == "late":
                    self.assertIn("Respuesta tardía", prefix)
                else:
                    self.assertIn("vigencia temporal no confirmada", prefix)

    def test_aware_datetime_and_equivalent_z_timestamp_are_accepted(self):
        self.require_implementation()
        now = datetime.fromisoformat("2026-10-11T15:00:00+02:00")
        aware_created_at = datetime.fromisoformat("2026-10-11T09:00:00+02:00")
        from_datetime = response_timing.late_response_prefix(aware_created_at, now=now)
        from_z_timestamp = response_timing.late_response_prefix(
            "2026-10-11T07:00:00Z", now=now
        )
        self.assertEqual(from_datetime, from_z_timestamp)

    def test_now_without_timezone_is_rejected(self):
        self.require_implementation()
        with self.assertRaises(ValueError):
            response_timing.late_response_prefix(
                "2026-10-11T09:00:00+02:00",
                now=datetime(2026, 10, 11, 15, 0),
            )

    def test_late_delivery_preserves_full_canonical_answer(self):
        self.require_implementation()
        answer = "Respuesta canónica completa. " * 120
        visible = response_timing.format_late_delivery(
            answer,
            "2026-10-11T09:00:00+02:00",
            now=datetime.fromisoformat("2026-10-11T15:00:00+02:00"),
        )
        self.assertTrue(visible.startswith("Respuesta tardía a tu consulta del "))
        self.assertTrue(visible.endswith(answer))

    def test_on_time_delivery_is_unchanged(self):
        self.require_implementation()
        answer = "Respuesta canónica."
        visible = response_timing.format_late_delivery(
            answer,
            "2026-10-11T09:00:00+02:00",
            now=datetime.fromisoformat("2026-10-11T13:59:00+02:00"),
        )
        self.assertEqual(visible, answer)
