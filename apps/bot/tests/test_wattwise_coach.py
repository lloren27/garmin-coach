from __future__ import annotations

import unittest

from app.coach import format_bike, format_fatigue, format_feedback, format_load, format_wattwise


SYNC = {
    "received_at": "2026-09-09T08:00:00+00:00",
    "payload": {
        "generated_at": "2026-09-09T10:00:00+02:00",
        "summary": {
            "activities": [
                {
                    "date": "2026-09-06",
                    "name": "Getafe Ciclismo en ruta",
                    "sport": "cycling",
                    "km": 67.05,
                    "duration_s": 7782,
                    "hours": 2.16,
                    "avg_speed_kmh": 31.0,
                    "avg_hr": 116,
                    "avg_power": 173,
                    "normalized_power": 226,
                    "training_effect": 2.3,
                }
            ],
            "week": {"hours": 2.2, "km": 67.1},
            "sports": {
                "running": {"sessions_7d": 1, "km_7d": 7.0, "hours_7d": 0.6},
                "cycling": {
                    "sessions_120d": 2,
                    "sessions_28d": 2,
                    "sessions_7d": 2,
                    "km_28d": 175.6,
                    "km_7d": 175.6,
                    "hours_28d": 6.1,
                    "hours_7d": 6.1,
                    "latest": {
                        "date": "2026-09-06",
                        "sport": "cycling",
                        "km": 67.05,
                        "duration_s": 7782,
                        "avg_speed_kmh": 31.0,
                        "avg_power": 173,
                        "normalized_power": 226,
                    },
                    "longest": {
                        "date": "2026-09-05",
                        "sport": "cycling",
                        "km": 108.5,
                        "duration_s": 14310,
                        "avg_speed_kmh": 27.3,
                    },
                },
                "strength": {"sessions_7d": 0, "hours_7d": 0},
            },
            "fatigue": {
                "level": "media",
                "hours_7d": 6.7,
                "weekly_avg_hours_28d": 5.0,
                "acute_chronic_ratio": 1.2,
                "hard_sessions_7d": 1,
                "days_since_rest": 2,
            },
        },
    },
}

WATTWISE = {
    "received_at": "2026-09-09T08:01:00+00:00",
    "payload": {
        "status": "ok",
        "generated_at": "2026-09-09T10:01:00+02:00",
        "cycling_power_metrics": [
            {"date": "2026-09-05", "tss": 189.9, "intensity_factor": 0.69, "variability_index": 1.29},
            {"date": "2026-09-06", "tss": 102.2, "intensity_factor": 0.69, "variability_index": 1.31},
        ],
        "latest_load": {"load": 102.2, "fitness": 10.4, "fatigue": 42.7, "form": -25.4},
        "fitness_signature": {"sport": "cycling", "effective_date": "2026-09-08", "ftp_w": 329},
    },
}


class WattwiseCoachTests(unittest.TestCase):
    def test_feedback_adds_wattwise_to_matching_cycling_activity(self) -> None:
        answer = format_feedback(SYNC, profile={"profile": {"ftp": 329}}, wattwise=WATTWISE)
        self.assertIn("Conclusion: Dia exigente", answer)
        self.assertIn("Wattwise confirma una carga ciclista significativa", answer)
        self.assertNotIn("TSS 102.2", answer)

    def test_running_feedback_does_not_attach_cycling_metric(self) -> None:
        running = {"date": "2026-09-06", "sport": "running", "km": 7.0, "duration_s": 2200, "pace": "5:14/km"}
        answer = format_feedback(SYNC, activity=running, wattwise=WATTWISE)
        self.assertNotIn("Wattwise:", answer)

    def test_bike_load_and_fatigue_surface_wattwise(self) -> None:
        self.assertIn("Wattwise ultima", format_bike(SYNC, wattwise=WATTWISE))
        self.assertIn("TSS total 292.1", format_load(SYNC, wattwise=WATTWISE))
        self.assertIn("forma -25.4", format_fatigue(SYNC, WATTWISE))

    def test_dedicated_command_explains_metrics(self) -> None:
        answer = format_wattwise(WATTWISE, SYNC, {"profile": {"ftp": 329}})
        self.assertIn("Analisis Wattwise", answer)
        self.assertIn("FTP Wattwise: 329 W desde 08/09/2026", answer)
        self.assertIn("carga ciclista reciente alta", answer)


if __name__ == "__main__":
    unittest.main()
