from __future__ import annotations

import unittest

from app.coach import (
    format_checkin_saved,
    format_feedback,
    format_strength,
    format_week,
    format_week_plan,
    parse_checkin,
)


DAILY_SYNC = {
    "received_at": "2026-09-09T19:15:00+00:00",
    "payload": {
        "generated_at": "2026-09-09T21:15:00+02:00",
        "race": {"days_until": 60, "target_pace": "5:13/km"},
        "wellness": {
            "sleep": {"sleep_seconds": 22200},
            "body_battery": {"charged": 12, "drained": 62},
            "stress": {"avg": 26},
        },
        "summary": {
            "activities": [
                {
                    "id": "bike-1",
                    "date": "2026-09-09",
                    "sport": "cycling",
                    "km": 40.05,
                    "duration_s": 6243,
                    "avg_speed_kmh": 23.1,
                    "training_effect": 2.1,
                },
                {
                    "id": "run-1",
                    "date": "2026-09-09",
                    "sport": "running",
                    "km": 12.01,
                    "duration_s": 3824,
                    "pace": "5:18/km",
                    "running_load": 135.6,
                },
            ],
            "week": {
                "start": "2026-09-07",
                "by_sport": {
                    "running": {"sessions": 3, "km": 29.0},
                    "cycling": {"sessions": 1, "hours": 1.7},
                    "strength": {"sessions": 1, "hours": 0.8},
                },
            },
            "weekly": [
                {"week": "2026-08-17", "long_run_km": 9.5},
                {"week": "2026-08-24", "long_run_km": 10.0},
                {"week": "2026-08-31", "long_run_km": 12.0},
                {"week": "2026-09-07", "long_run_km": 12.0},
            ],
            "fatigue": {
                "level": "media",
                "acute_chronic_ratio": 1.52,
                "days_since_rest": 7,
            },
            "running_load": {"available": True, "acwr_status": "elevada"},
            "next_workout": {
                "title": "Descanso o rodaje regenerativo",
                "details": "Descanso o 30-45 min muy facil, sin series ni tempo.",
            },
        },
    },
}


class DailyFeedbackTests(unittest.TestCase):
    def test_feedback_aggregates_all_daily_activities_and_health(self) -> None:
        old_scores = [{"checkin": {"rpe": 9, "sleep": 2, "energy": 2, "raw": "rpe 9 sueno 2 energia 2"}}]
        answer = format_feedback(DAILY_SYNC, old_scores)

        self.assertIn("2 sesiones, 2 h 48 min", answer)
        self.assertIn("running 12 km", answer)
        self.assertIn("bici 40 km", answer)
        self.assertIn("la carrera fue el estimulo principal", answer)
        self.assertIn("Recuperacion Garmin: limitada", answer)
        self.assertIn("sueno algo corto", answer)
        self.assertNotIn("Contexto subjetivo", answer)
        self.assertNotIn("RPE", answer)
        self.assertNotIn("energia 2", answer)

    def test_only_injury_information_survives_from_checkin(self) -> None:
        checkins = [
            {
                "checkin": {
                    "rpe": 9,
                    "sleep": 2,
                    "energy": 2,
                    "pain": "gemelo derecho",
                    "note": "aparece al correr",
                }
            }
        ]
        answer = format_feedback(DAILY_SYNC, checkins)

        self.assertIn("Molestias reportadas: dolor gemelo derecho, nota aparece al correr", answer)
        self.assertIn("descanso o trabajo muy suave", answer)
        self.assertNotIn("RPE", answer)

    def test_new_checkins_do_not_store_subjective_recovery_scores(self) -> None:
        checkin = parse_checkin("rpe 9 sueno 2 energia 2 dolor gemelo nota al correr", "user-1")
        self.assertNotIn("rpe", checkin)
        self.assertNotIn("sleep", checkin)
        self.assertNotIn("energy", checkin)
        self.assertEqual(checkin["pain"], "gemelo")
        self.assertEqual(checkin["note"], "al correr")
        saved = format_checkin_saved({"checkin": checkin})
        self.assertIn("la recuperacion sale de Garmin", saved)


class WeeklyPlanTests(unittest.TestCase):
    def test_week_plan_covers_seven_days_and_prescribes_strength(self) -> None:
        answer = format_week_plan(DAILY_SYNC, {"profile": {"marathon_goal": "3:35"}})

        self.assertIn("Plan 7 dias (10/09/2026-16/09/2026)", answer)
        self.assertIn("Enfoque: asimilar carga", answer)
        self.assertIn("Jue 10/09/2026: Descanso o rodaje regenerativo", answer)
        self.assertIn("Dom 13/09/2026: tirada de 14 km facil", answer)
        self.assertIn("Mie 16/09/2026: running 35-45 min facil + fuerza full body A", answer)

    def test_week_command_combines_completed_balance_and_future_plan(self) -> None:
        answer = format_week(DAILY_SYNC)
        self.assertIn("Has hecho 3 carreras", answer)
        self.assertIn("Plan 7 dias", answer)

    def test_strength_command_gives_complete_full_body_guidance(self) -> None:
        answer = format_strength(DAILY_SYNC)
        self.assertIn("Sesion A: sentadilla, peso muerto rumano", answer)
        self.assertIn("Sesion B: zancada o split squat", answer)
        self.assertIn("2-3 repeticiones en reserva", answer)
        self.assertIn("al menos 48 h antes de la tirada larga", answer)


if __name__ == "__main__":
    unittest.main()
