from __future__ import annotations

import unittest
from datetime import date, timedelta

from garmin_sync.running_analytics import enrich_running_load


class RunningAnalyticsTests(unittest.TestCase):
    def test_uses_one_consistent_trimp_model_when_profile_is_available(self) -> None:
        today = date(2026, 9, 9)
        activities = [
            {
                "id": "run-direct",
                "date": today.isoformat(),
                "name": "Carrera con carga",
                "sport": "running",
                "duration_s": 3600,
                "avg_hr": 150,
                "training_load": 88,
            },
            {
                "id": "run-estimated",
                "date": (today - timedelta(days=2)).isoformat(),
                "name": "Carrera sin carga",
                "sport": "running",
                "duration_s": 3000,
                "avg_hr": 145,
            },
            {
                "id": "bike",
                "date": today.isoformat(),
                "sport": "cycling",
                "duration_s": 7200,
                "avg_hr": 140,
            },
        ]
        enriched, summary = enrich_running_load(
            activities,
            {"profile": {"sex": "hombre", "max_hr": 180, "resting_hr": 50}},
            today,
        )

        self.assertNotEqual(enriched[0]["running_load"], 88)
        self.assertEqual(enriched[0]["running_load_source"], "trimp_estimado")
        self.assertGreater(enriched[1]["running_load"], 0)
        self.assertEqual(enriched[1]["running_load_source"], "trimp_estimado")
        self.assertNotIn("running_load", enriched[2])
        self.assertEqual(summary["model"], "trimp_estimado")
        self.assertEqual(summary["unit"], "TRIMP")
        self.assertEqual(summary["source_counts_28d"], {"garmin": 0, "estimated_trimp": 2})
        self.assertEqual(summary["running_days_7d"], 2)
        self.assertGreater(summary["acute_load_7d"], 0)

    def test_uses_garmin_load_only_when_trimp_cannot_be_calculated(self) -> None:
        activity = {
            "id": "run",
            "date": "2026-09-09",
            "sport": "running",
            "duration_s": 3600,
            "avg_hr": 145,
            "training_load": 88,
        }
        enriched, summary = enrich_running_load([activity], {}, date(2026, 9, 9))
        self.assertEqual(enriched[0]["running_load"], 88)
        self.assertEqual(enriched[0]["running_load_source"], "garmin")
        self.assertEqual(summary["model"], "garmin")

    def test_requires_profile_when_garmin_load_is_missing(self) -> None:
        activity = {
            "id": "run",
            "date": "2026-09-09",
            "sport": "running",
            "duration_s": 3600,
            "avg_hr": 145,
        }
        enriched, summary = enrich_running_load([activity], {}, date(2026, 9, 9))
        self.assertNotIn("running_load", enriched[0])
        self.assertFalse(summary["available"])


if __name__ == "__main__":
    unittest.main()
