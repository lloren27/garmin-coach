from __future__ import annotations

import unittest

from app.coach import format_adjust, format_fatigue, format_feedback, format_latest, format_running


SYNC = {
    "received_at": "2026-09-09T08:00:00+00:00",
    "payload": {
        "generated_at": "2026-09-09T10:00:00+02:00",
        "summary": {
            "activities": [
                {
                    "id": "run-1",
                    "date": "2026-09-09",
                    "name": "Madrid Carrera",
                    "sport": "running",
                    "km": 12.01,
                    "duration_s": 3822,
                    "pace": "5:18/km",
                    "avg_hr": 144,
                    "running_load": 135.6,
                    "running_load_source": "trimp_estimado",
                    "hr_reserve_pct": 77,
                }
            ],
            "sports": {"running": {"sessions_7d": 5, "km_7d": 49.5, "hours_7d": 4.5}},
            "running_load": {
                "available": True,
                "acute_load_7d": 496.5,
                "chronic_weekly_load_28d": 364.9,
                "acwr": 1.36,
                "acwr_status": "elevada",
                "monotony_7d": 1.47,
                "strain_7d": 729.9,
                "running_days_7d": 5,
                "source_counts_28d": {"garmin": 0, "estimated_trimp": 18},
                "profile_basis": {"max_hr": 171, "resting_hr": 56, "sex": "hombre"},
                "latest": {
                    "date": "2026-09-09",
                    "load": 135.6,
                    "source": "trimp_estimado",
                },
            },
            "fatigue": {"level": "media"},
        },
    },
}


class RunningCoachTests(unittest.TestCase):
    def test_feedback_surfaces_estimated_load(self) -> None:
        answer = format_feedback(SYNC)
        self.assertIn("Conclusion: Dia exigente", answer)
        self.assertIn("carrera exigente por carga cardiovascular", answer)
        self.assertIn("no conviene anadir otra sesion dura", answer)
        self.assertIn("Decision: manana descanso o 30-45 min muy faciles", answer)

    def test_latest_surfaces_load_without_error(self) -> None:
        answer = format_latest(SYNC)
        self.assertIn("Carga running: 135.6", answer)

    def test_running_command_explains_provenance_and_acwr(self) -> None:
        answer = format_running(SYNC)
        self.assertIn("ACWR: 1.36 (subida de carga)", answer)
        self.assertIn("TRIMP estimado 18", answer)
        self.assertIn("no predice por si solo una lesion", answer)

    def test_fatigue_turns_elevated_running_load_into_advice(self) -> None:
        answer = format_fatigue(SYNC)
        self.assertIn("Running: carga 7d 496.5, ACWR 1.36", answer)
        self.assertIn("haz facil el siguiente entreno", answer)

    def test_adjust_uses_high_latest_running_load_as_risk(self) -> None:
        answer = format_adjust(SYNC)
        self.assertIn("Riesgo estimado: medio (3/7)", answer)
        self.assertIn("carga cardiovascular alta en la ultima carrera", answer)


if __name__ == "__main__":
    unittest.main()
