from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from garmin_sync.zepp_provider import ZeppAPIError, ZeppAuthError, ZeppProvider


VALID_SLEEP = {
    "start": "2026-09-21T23:41:00+02:00",
    "end": "2026-09-22T07:09:00+02:00",
    "total_minutes": 448,
    "deep_minutes": 82,
    "light_minutes": 244,
    "rem_minutes": 96,
    "awake_minutes": 26,
    "sleep_score": 84,
    "resting_hr": 47,
}
VALID_STEPS = {"steps": 8231}
MADRID = ZoneInfo("Europe/Madrid")


class FakeZeppClient:
    def get_sleep(self, _day: str) -> dict:
        return VALID_SLEEP

    def get_steps(self, _day: str) -> dict:
        return VALID_STEPS

    def get_stress(self, _start: str, _end: str) -> list[dict]:
        return []

    def get_training_load(self, _start: str, _end: str) -> list[dict]:
        return []

    def get_phn(self, _start: str, _end: str) -> list[dict]:
        return []

    def get_sport_load(self, _start: str, _end: str) -> list[dict]:
        return []

    def get_vo2_max(self, _start: str, _end: str) -> list[dict]:
        return []


class RaisingZeppClient(FakeZeppClient):
    def get_sleep(self, _day: str) -> dict:
        raise ZeppAuthError("expired secret-token")


class NetworkFailingZeppClient(FakeZeppClient):
    def get_sleep(self, _day: str) -> dict:
        try:
            raise requests.ConnectionError("network unavailable")
        except requests.ConnectionError as cause:
            raise ZeppAPIError("request failed") from cause


class RealShapeZeppClient(FakeZeppClient):
    def get_sleep(self, _day: str) -> dict:
        return {
            "date": "2026-09-22",
            "start": "2026-09-21T23:41:00",
            "end": "2026-09-22T07:09:00",
            "duration_minutes": 448,
            "deep_minutes": 82,
            "light_minutes": 244,
            "sleep_score": 84,
            "resting_hr": 47,
            "stages": [
                {"stage": "deep", "duration_minutes": 82},
                {"stage": "light", "duration_minutes": 244},
                {"stage": "rem", "duration_minutes": 96},
                {"stage": "awake", "duration_minutes": 26},
            ],
            "nap_stages": [],
        }

    def get_stress(self, _start: str, _end: str) -> list[dict]:
        return [{"timestamp": "2026-09-22", "avg_stress": 31, "min_stress": 12, "max_stress": 74, "readings": [12, 31, 74], "zone_percentages": {"low": 40, "medium": 30, "high": 30}}]

    def get_sport_load(self, _start: str, _end: str) -> list[dict]:
        return [{"date": "2026-09-22", "daily_load": 82, "weekly_load": 300}]


class InvalidSelectedSleepZeppClient(FakeZeppClient):
    def get_sleep(self, _day: str) -> dict:
        return {
            "start": "2026-09-22T00:00:00",
            "end": "2026-09-22T00:00:00",
            "duration_minutes": 0,
        }

    def get_band_data(self, day: str) -> dict:
        if day != "2026-09-23":
            return {"date": day, "summary": {}}
        start = int(datetime(2026, 9, 22, 23, 41, tzinfo=MADRID).timestamp())
        end = int(datetime(2026, 9, 23, 7, 9, tzinfo=MADRID).timestamp())
        return {
            "date": day,
            "summary": {
                "slp": {
                    "st": start,
                    "ed": end,
                    "rhr": 47,
                    "ss": 84,
                    "dp": 82,
                    "lt": 244,
                    "stage": [
                        {"start": 0, "stop": 82, "mode": 5},
                        {"start": 82, "stop": 326, "mode": 4},
                        {"start": 326, "stop": 422, "mode": 8},
                        {"start": 422, "stop": 448, "mode": 7},
                    ],
                }
            },
        }


class TimestampedTrainingLoadZeppClient(FakeZeppClient):
    def get_training_load(self, _start: str, _end: str) -> list[dict]:
        return [
            {
                "timestamp": int(datetime(2026, 9, 22, 12, tzinfo=MADRID).timestamp() * 1000),
                "atl": 31,
                "ctl": 29,
                "tsb": -2,
                "recovery_factor": 0.5,
            },
            {
                "timestamp": int(datetime(2026, 9, 23, 12, tzinfo=MADRID).timestamp() * 1000),
                "atl": 42,
                "ctl": 37,
                "tsb": -5,
                "recovery_factor": 0.82,
            },
        ]


class ZeppProviderTests(unittest.TestCase):
    def test_fetch_days_marks_rest_day_ok_when_vo2max_is_absent(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42", base_url="https://example.test")
        provider._client = FakeZeppClient()

        days, status = provider.fetch_days([date(2026, 9, 22)])

        self.assertEqual(days["2026-09-22"].status, "ok")
        self.assertEqual(days["2026-09-22"].data.to_dict()["steps"]["value"], 8231)
        self.assertEqual(status["days_received"], 1)
        self.assertEqual(status["status"], "ok")

    def test_auth_failure_is_redacted_and_does_not_include_token(self) -> None:
        provider = ZeppProvider(token="secret-token", user_id="42")
        provider._client = RaisingZeppClient()

        days, status = provider.fetch_days([date(2026, 9, 22)])

        self.assertEqual(days["2026-09-22"].status, "error")
        self.assertEqual(status["status"], "auth_error")
        self.assertNotIn("secret-token", repr(status))

    def test_wrapped_network_failure_is_classified_as_network_error(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42")
        provider._client = NetworkFailingZeppClient()

        _days, status = provider.fetch_days([date(2026, 9, 22)])

        self.assertEqual(status["status"], "network_error")

    def test_zero_steps_are_preserved_as_a_valid_measurement(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42")
        provider._client = FakeZeppClient()
        provider._client.get_steps = lambda _day: {"steps": 0}

        days, _status = provider.fetch_days([date(2026, 9, 22)])

        self.assertEqual(days["2026-09-22"].data.to_dict()["steps"]["value"], 0)

    def test_normalizes_real_zepp_sleep_stages_and_stress_coverage(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42", timezone_name="Europe/Madrid")
        provider._client = RealShapeZeppClient()

        days, _status = provider.fetch_days([date(2026, 9, 22)])
        data = days["2026-09-22"].data.to_dict()

        self.assertEqual(data["sleep"]["total_minutes"], 448)
        self.assertEqual(data["sleep"]["rem_minutes"], 96)
        self.assertEqual(data["sleep"]["awake_minutes"], 26)
        self.assertTrue(data["sleep"]["end"].endswith("+02:00"))
        self.assertEqual(data["stress"]["sample_count"], 3)
        self.assertEqual(data["stress"]["coverage_minutes"], 15)
        self.assertEqual(data["sport_load"]["value"], 82)

    def test_falls_back_to_valid_band_sleep_when_export_selects_an_empty_session(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42", timezone_name="Europe/Madrid")
        provider._client = InvalidSelectedSleepZeppClient()

        days, _status = provider.fetch_days([date(2026, 9, 23)])
        sleep = days["2026-09-23"].data.to_dict()["sleep"]

        self.assertEqual(sleep["total_minutes"], 448)
        self.assertEqual(sleep["deep_minutes"], 82)
        self.assertEqual(sleep["rem_minutes"], 96)
        self.assertTrue(sleep["end"].startswith("2026-09-23T07:09:00"))

    def test_selects_training_load_for_the_requested_timestamp_date(self) -> None:
        provider = ZeppProvider(token="secret", user_id="42", timezone_name="Europe/Madrid")
        provider._client = TimestampedTrainingLoadZeppClient()

        days, _status = provider.fetch_days([date(2026, 9, 23)])
        training_load = days["2026-09-23"].data.to_dict()["training_load"]

        self.assertEqual(training_load["atl"], 42)
        self.assertEqual(training_load["recovery_factor"], 0.82)

    def test_missing_credentials_disable_provider_without_client(self) -> None:
        provider = ZeppProvider(token="", user_id="")

        days, status = provider.fetch_days([date(2026, 9, 22)])

        self.assertEqual(days, {})
        self.assertEqual(status["status"], "disabled")
        self.assertEqual(status["days_requested"], 1)
        self.assertEqual(status["days_received"], 0)


if __name__ == "__main__":
    unittest.main()
