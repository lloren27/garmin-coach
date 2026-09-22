from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from garmin_sync import sync
from garmin_sync.sync import collect_wellness_history
from garmin_sync.wellness_models import NormalizedWellness, ProviderDayResult


DATES = [date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22)]
GARMIN_SLEEP = {
    "dailySleepDTO": {
        "sleepTimeSeconds": 27000,
        "deepSleepSeconds": 4800,
        "lightSleepSeconds": 15000,
        "remSleepSeconds": 5700,
        "awakeSleepSeconds": 1500,
        "sleepStartTimestampGMT": 1758483000000,
        "sleepEndTimestampGMT": 1758510000000,
    },
    "sleepScores": {"overall": {"value": 80}},
}


class FakeGarmin:
    def __init__(self, sleeps: dict[str, dict] | None = None) -> None:
        self.sleeps = sleeps or {}

    def get_user_summary(self, day: str) -> dict:
        return {"totalSteps": 5000, "restingHeartRate": 50, "calendarDate": day}

    def login(self, _tokenstore: str) -> None:
        return None

    def get_sleep_data(self, day: str) -> dict:
        return self.sleeps.get(day, {})

    def get_rhr_day(self, day: str) -> dict:
        return {"restingHeartRate": 50, "calendarDate": day}

    def get_stress_data(self, _day: str) -> dict:
        return {"avgStressLevel": 30}

    def get_all_day_stress(self, _day: str) -> dict:
        return {}

    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: {}


class FakeZeppProvider:
    def fetch_days(self, dates: list[date]):
        results = {
            day.isoformat(): ProviderDayResult(
                date=day.isoformat(),
                status="ok",
                data=NormalizedWellness(
                    steps={"value": 8000, "unit": "steps", "source": "zepp", "observed_at": day.isoformat()}
                ),
            )
            for day in dates
        }
        return results, {"status": "ok", "days_requested": len(dates), "days_received": len(dates)}


class NoZeppSleep(FakeZeppProvider):
    pass


class OneDayFailsProvider(FakeZeppProvider):
    def fetch_days(self, dates: list[date]):
        results, _status = super().fetch_days(dates)
        failed = dates[1].isoformat()
        results[failed] = ProviderDayResult(date=failed, status="error", error_kind="api_error")
        return results, {"status": "partial", "days_requested": 3, "days_received": 2}


class AuthErrorZeppProvider:
    def fetch_days(self, dates: list[date]):
        results = {
            day.isoformat(): ProviderDayResult(date=day.isoformat(), status="error", error_kind="auth_error")
            for day in dates
        }
        return results, {"status": "auth_error", "days_requested": len(dates), "days_received": 0}


class ZeppSyncPayloadTests(unittest.TestCase):
    def test_today_effective_aliases_the_resolved_history_for_today(self) -> None:
        wellness = collect_wellness_history(FakeGarmin(), DATES, FakeZeppProvider(), "Europe/Madrid")

        self.assertIs(wellness["effective"], wellness["history"]["2026-09-22"]["effective"])
        self.assertEqual(wellness["schema_version"], 2)
        self.assertEqual(wellness["timezone"], "Europe/Madrid")
        self.assertEqual(wellness["effective"]["steps"]["source"], "zepp")

    def test_historical_garmin_sleep_falls_back_for_same_date(self) -> None:
        wellness = collect_wellness_history(
            FakeGarmin(sleeps={"2026-09-21": GARMIN_SLEEP}),
            DATES,
            NoZeppSleep(),
            "Europe/Madrid",
        )

        self.assertEqual(wellness["history"]["2026-09-21"]["effective"]["sleep"]["source"], "garmin")

    def test_one_provider_day_failure_is_partial_not_a_failed_history(self) -> None:
        wellness = collect_wellness_history(FakeGarmin(), DATES, OneDayFailsProvider(), "Europe/Madrid")

        status = wellness["provider_status"]["zepp"]
        self.assertEqual(status["status"], "partial")
        self.assertEqual((status["days_requested"], status["days_received"]), (3, 2))
        self.assertIn("2026-09-21", wellness["history"])

    def test_build_payload_keeps_only_garmin_activities_when_zepp_has_motion(self) -> None:
        fake_client = FakeGarmin()
        summary = {
            "activities": [{"id": "garmin-activity-1"}],
            "avg_weekly_km_8w": 0,
            "longest_120d": [],
        }
        with (
            patch.object(sync, "Garmin", return_value=fake_client),
            patch.object(sync, "get_activities", return_value=[]),
            patch.object(sync, "summarize", return_value=summary),
            patch.object(sync, "load_remote_profile", return_value={}),
            patch.object(sync, "compact_physiology", return_value={}),
            patch.object(sync, "ZeppProvider", return_value=FakeZeppProvider()),
            patch.object(sync, "TODAY", date(2026, 9, 22)),
        ):
            payload = sync.build_payload()

        self.assertEqual(payload["wellness"]["schema_version"], 2)
        self.assertEqual(payload["summary"]["activities"], [{"id": "garmin-activity-1"}])
        self.assertNotIn("zepp-motion-1", str(payload["summary"]["activities"]))

    def test_end_to_end_auth_error_keeps_garmin_activity_and_allowed_fallbacks(self) -> None:
        fake_client = FakeGarmin(sleeps={"2026-09-22": GARMIN_SLEEP})
        summary = {
            "activities": [{"id": "garmin-activity-1"}],
            "avg_weekly_km_8w": 0,
            "longest_120d": [],
        }
        with (
            patch.object(sync, "Garmin", return_value=fake_client),
            patch.object(sync, "get_activities", return_value=[]),
            patch.object(sync, "summarize", return_value=summary),
            patch.object(sync, "load_remote_profile", return_value={}),
            patch.object(sync, "compact_physiology", return_value={}),
            patch.object(sync, "ZeppProvider", return_value=AuthErrorZeppProvider()),
            patch.object(sync, "TODAY", date(2026, 9, 22)),
        ):
            payload = sync.build_payload()

        self.assertEqual(payload["wellness"]["provider_status"]["zepp"]["status"], "auth_error")
        self.assertEqual(payload["summary"]["activities"], [{"id": "garmin-activity-1"}])
        self.assertEqual(payload["wellness"]["effective"]["sleep"]["source"], "garmin")
        self.assertNotIn("stress", payload["wellness"]["effective"])


if __name__ == "__main__":
    unittest.main()
