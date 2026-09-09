from __future__ import annotations

import unittest

from garmin_sync.sync import TODAY, recommend_next_workout


class RunningRecommendationTests(unittest.TestCase):
    def test_high_running_load_today_overrides_calendar_workout(self) -> None:
        recommendation = recommend_next_workout(
            [],
            {
                "available": True,
                "acwr_status": "elevada",
                "latest": {"date": TODAY.isoformat(), "load": 135.6},
            },
        )

        self.assertEqual(recommendation["title"], "Descanso o rodaje regenerativo")
        self.assertIn("carga cardiovascular", recommendation["reason"])

    def test_elevated_acwr_selects_easy_run(self) -> None:
        recommendation = recommend_next_workout(
            [],
            {
                "available": True,
                "acwr_status": "elevada",
                "latest": {"date": "2026-09-08", "load": 90},
            },
        )

        self.assertEqual(recommendation["title"], "Rodaje facil")
        self.assertIn("7 dias", recommendation["reason"])


if __name__ == "__main__":
    unittest.main()
