import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import experience


NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


class DelayNoticeViewTests(unittest.TestCase):
    def setUp(self):
        self.sync = {
            "received_at": "2026-10-11T11:59:00+00:00",
            "payload": {
                "generated_at": "2026-10-11T11:55:00+00:00",
                "summary": {
                    "activities": [
                        {
                            "id": "private-activity-id",
                            "date": "2026-10-11",
                            "name": "PRIVATE ACTIVITY NAME",
                            "sport": "running",
                            "km": 12.01,
                            "duration_s": 3824,
                            "avg_hr": 144,
                            "source": "garmin",
                            "notes": "PRIVATE NOTE",
                        },
                        {
                            "id": "other-private-id",
                            "date": "2026-10-10",
                            "sport": "cycling",
                            "km": 40.05,
                            "duration_s": 6243,
                            "source": "strava",
                        },
                    ]
                },
            },
        }

    def test_latest_available_view_is_factual_dated_and_redacts_free_text(self):
        result = experience.format_factual_view(
            self.sync, scope="latest_available", now=NOW
        )

        for fact in (
            "Últimos datos disponibles",
            "11/10/2026 13:55",
            "hace 5 min",
            "carrera",
            "12.01 km",
            "FC media: 144 lpm",
            "Garmin",
            "ciclismo",
            "40.05 km",
            "Strava",
        ):
            self.assertIn(fact, result)
        for private_value in (
            "private-activity-id",
            "PRIVATE ACTIVITY NAME",
            "PRIVATE NOTE",
        ):
            self.assertNotIn(private_value, result)
        self.assertLess(len(result), 4096)
        self.assertNotIn("Recomendación", result)
        self.assertNotIn("Conclusión", result)

    def test_old_sync_keeps_absolute_freshness_and_missing_sync_does_not_invent_data(self):
        old = {
            "received_at": "2026-10-08T12:00:00+00:00",
            "payload": {"generated_at": "2026-10-08T12:00:00+00:00", "summary": {"activities": []}},
        }
        old_result = experience.format_factual_view(
            old, scope="latest_available", now=NOW
        )
        self.assertIn("08/10/2026 14:00", old_result)
        self.assertIn("hace 4320 min", old_result)
        self.assertIn("No hay actividades", old_result)

        missing_result = experience.format_factual_view(
            None, scope="latest_available", now=NOW
        )
        self.assertIn("vigencia no confirmada", missing_result)
        self.assertIn("No hay actividades", missing_result)

    def test_bad_dates_and_missing_wellness_are_neutral(self):
        sync = {
            "received_at": "not-a-date",
            "payload": {
                "generated_at": "2027-01-01T00:00:00Z",
                "summary": {"activities": []},
                "wellness": None,
                "activity_provider_status": {"garmin": {"last_error": "PRIVATE ERROR"}},
            },
        }
        result = experience.format_factual_view(
            sync, scope="latest_available", now=NOW
        )
        self.assertIn("vigencia no confirmada", result)
        self.assertIn("No hay actividades", result)
        self.assertNotIn("PRIVATE ERROR", result)

    def test_factual_view_includes_recent_wellness_measurements_with_date_and_source(self):
        self.sync["payload"]["wellness"] = {
            "provider_status": {
                "garmin": {"status": "api_error"},
                "zepp": {"status": "api_error"},
            },
            "history": {
                "2026-10-10": {
                    "effective": {
                        "date": "2026-10-10",
                        "resting_hr": {"value": 47, "unit": "bpm", "source": "zepp"},
                        "steps": {"value": 8532, "unit": "steps", "source": "garmin"},
                        "sleep": {"total_minutes": 452, "source": "zepp"},
                        "stress": {"avg": 22, "source": "zepp"},
                    }
                }
            },
        }

        result = experience.format_factual_view(
            self.sync, scope="latest_available", now=NOW
        )

        self.assertIn("2026-10-10", result)
        self.assertIn("FC en reposo: 47 lpm (Zepp)", result)
        self.assertIn("Pasos: 8532 (Garmin)", result)
        self.assertIn("Sueño: 7 h 32 min (Zepp)", result)
        self.assertIn("Estrés medio: 22 (Zepp)", result)
        self.assertNotIn("estado factual no disponible", result)

    def test_wellness_view_ignores_invalid_or_untrusted_values_and_is_bounded(self):
        self.sync["payload"]["wellness"] = {
            "history": {
                f"2026-10-{day:02d}": {
                    "effective": {
                        "resting_hr": {"value": 9999, "source": "zepp"},
                        "steps": {"value": 100000000, "source": "garmin"},
                        "stress": {"avg": 22, "source": "PRIVATE SOURCE"},
                    }
                }
                for day in range(1, 12)
            },
            "provider_status": {"garmin": {"status": "error"}},
        }

        result = experience.format_factual_view(
            self.sync, scope="latest_available", now=NOW
        )

        self.assertNotIn("9999", result)
        self.assertNotIn("100000000", result)
        self.assertNotIn("PRIVATE SOURCE", result)
        self.assertLess(len(result), 4096)

    def test_large_history_and_untrusted_names_stay_within_telegram_limit(self):
        many = {
            "payload": {
                "generated_at": "2026-10-11T11:00:00Z",
                "summary": {
                    "activities": [
                        {
                            "date": "2026-10-11",
                            "name": "x" * 20_000,
                            "sport": "running",
                            "km": 10,
                            "duration_s": 3600,
                            "source": "garmin",
                        }
                        for _ in range(500)
                    ]
                },
            }
        }
        result = experience.format_factual_view(
            many, scope="latest_available", now=NOW
        )
        self.assertLess(len(result), 4096)
        self.assertEqual(result.count("• "), 5)
        self.assertNotIn("x" * 100, result)

    def test_unsupported_scope_and_naive_now_are_rejected(self):
        with self.assertRaises(ValueError):
            experience.format_factual_view(self.sync, scope="today", now=NOW)
        with self.assertRaises(ValueError):
            experience.format_factual_view(
                self.sync, scope="latest_available", now=datetime(2026, 10, 11)
            )

    def test_notice_uses_generic_view_for_text_coach_voice_and_adjust_jobs(self):
        jobs = [
            {"source_kind": "text", "created_at": "2026-10-11T11:30:00Z",
             "chat_id": "PRIVATE CHAT", "text": question}
            for question in (
                "PRIVATE QUESTION free text",
                "PRIVATE QUESTION /coach",
                "PRIVATE QUESTION voice transcript",
                "PRIVATE QUESTION /ajustar",
                "PRIVATE QUESTION command without a persisted alias scope",
            )
        ]
        jobs[2]["source_kind"] = "voice"
        with patch.object(
            experience, "format_factual_view", wraps=experience.format_factual_view
        ) as render:
            for job in jobs:
                result = experience.format_delay_notice(job, self.sync, now=NOW)
                self.assertIn("consulta sigue en cola", result.lower())
                self.assertIn("últimos datos disponibles", result.lower())
                self.assertNotIn("PRIVATE CHAT", result)
                self.assertNotIn("PRIVATE QUESTION", result)
            self.assertEqual(
                [call.kwargs["scope"] for call in render.call_args_list],
                ["latest_available"] * len(jobs),
            )

    def test_no_coaching_renderers_or_resolver_are_imported_by_view_module(self):
        for name in (
            "resolve_intent",
            "format_feedback",
            "format_fatigue",
            "format_week",
        ):
            self.assertNotIn(name, experience.__dict__)


if __name__ == "__main__":
    unittest.main()
