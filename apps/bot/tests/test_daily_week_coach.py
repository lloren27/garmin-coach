from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

from app.coach import (
    build_ai_brief,
    format_checkin_saved,
    format_feedback,
    format_health,
    format_latest,
    format_strength,
    format_today,
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


ZEPPCENTRIC_SYNC = {
    "payload": {
        "wellness": {
            "schema_version": 2,
            "timezone": "Europe/Madrid",
            "effective": {
                "sleep": {
                    "total_minutes": 448,
                    "deep_minutes": 82,
                    "rem_minutes": 96,
                    "light_minutes": 248,
                    "awake_minutes": 22,
                    "score": 84,
                    "source": "zepp",
                },
                "resting_hr": {"value": 47, "unit": "bpm", "source": "zepp"},
                "steps": {"value": 8231, "unit": "steps", "source": "zepp"},
                "stress": {"avg": 23, "source": "zepp"},
                "atl": {"value": 42, "source": "zepp"},
                "ctl": {"value": 37, "source": "zepp"},
                "tsb": {"value": -5, "source": "zepp"},
                "trimp": {"value": 68, "source": "zepp"},
                "sport_load": {"value": 95, "source": "zepp"},
                "recovery_factor": {"value": 0.82, "source": "zepp"},
                "vo2max": {"value": 52, "unit": "ml/kg/min", "source": "garmin"},
            },
        },
        "summary": {
            "today": {"date": "2026-09-22", "activities": [{"id": "run-1"}]},
            "activities": [{"id": "run-1", "date": "2026-09-22", "sport": "running"}],
            "fatigue": {"level": "media"},
            "next_workout": {"title": "Rodaje facil"},
        },
    }
}


class DailyFeedbackTests(unittest.TestCase):
    def test_latest_zepp_activity_is_labelled_and_keeps_common_metrics(self) -> None:
        sync = deepcopy(DAILY_SYNC)
        sync["payload"]["summary"]["activities"] = [
            {
                "id": "zepp:run:track-42",
                "source": "zepp",
                "source_activity_id": "track-42",
                "date": "2026-09-09",
                "name": "Correr al aire libre",
                "sport": "running",
                "km": 8.02,
                "duration_s": 2518,
                "pace": "5:14/km",
                "avg_hr": 151,
            }
        ]

        answer = format_latest(sync)

        self.assertIn("[Zepp]", answer)
        self.assertIn("Distancia: 8.02 km", answer)
        self.assertIn("Pulso medio: 151 ppm", answer)
        self.assertNotIn("Training effect:", answer)
        self.assertNotIn("Wattwise", answer)
        self.assertNotIn("Potencia", answer)

    def test_today_and_feedback_label_zepp_activities_but_garmin_stays_unsuffixed(self) -> None:
        sync = deepcopy(DAILY_SYNC)
        zepp_run = {
            "id": "zepp:run:track-42",
            "source": "zepp",
            "date": "2026-09-09",
            "sport": "running",
            "km": 8.02,
            "duration_s": 2518,
            "pace": "5:14/km",
        }
        sync["payload"]["summary"]["activities"] = [zepp_run]
        sync["payload"]["summary"]["today"] = {
            "date": "2026-09-09",
            "activities": [zepp_run],
            "training_minutes": 42,
            "km": 8.0,
        }

        self.assertIn("Actividades: 1 [Zepp]", format_today(sync))
        self.assertIn("[Zepp]", format_feedback(sync))
        self.assertNotIn("[Zepp]", format_latest(DAILY_SYNC))

    def test_today_labels_effective_zepp_health_but_keeps_garmin_activities(self) -> None:
        answer = format_today(ZEPPCENTRIC_SYNC)

        self.assertIn("Sueno: 7 h 28 min [Zepp]", answer)
        self.assertIn("FC reposo: 47 bpm [Zepp]", answer)
        self.assertIn("Actividades: 1", answer)

    def test_health_labels_effective_metrics_and_legacy_payload_still_formats(self) -> None:
        answer = format_health(ZEPPCENTRIC_SYNC)
        legacy_answer = format_health(DAILY_SYNC)

        self.assertIn("Sueno: total 7 h 28 min [Zepp]", answer)
        self.assertIn("VO2max: 52 ml/kg/min [Garmin]", answer)
        self.assertIn("Carga Zepp: ATL 42, CTL 37, TSB -5 [Zepp]", answer)
        self.assertIn("TRIMP: 68 [Zepp]", answer)
        self.assertIn("Sport Load: 95 [Zepp]", answer)
        self.assertIn("Factor recuperacion: 0.82 [Zepp]", answer)
        self.assertIn("Salud y recuperacion Garmin", legacy_answer)

    def test_ai_brief_includes_source_labelled_effective_wellness(self) -> None:
        brief = build_ai_brief("¿entreno hoy?", ZEPPCENTRIC_SYNC, {}, [], [], None, None, None, None)
        content = "\n".join(section["content"] for section in brief["sections"])

        self.assertIn("Sueno: total 7 h 28 min [Zepp]", content)
        self.assertIn("VO2max: 52 ml/kg/min [Garmin]", content)
        self.assertIn("Factor recuperacion: 0.82 [Zepp]", content)
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
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 13, 12, tzinfo=tz)

        with patch("app.coach.datetime", FixedDatetime):
            answer = format_week_plan(DAILY_SYNC, {"profile": {"marathon_goal": "3:35"}})

        self.assertIn("Plan 7 dias (13/09/2026-19/09/2026)", answer)
        self.assertIn("Enfoque: asimilar carga", answer)
        self.assertIn("Dom 13/09/2026: Tirada larga", answer)
        self.assertIn("Lun 14/09/2026: Descanso y movilidad", answer)
        self.assertIn("Sab 19/09/2026: Rodaje fácil con progresivos", answer)
        self.assertIn("Fuerza: 1 sesion planificadas", answer)
        self.assertNotIn("10/09/2026", answer)

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
