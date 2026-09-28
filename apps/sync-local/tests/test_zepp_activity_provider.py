from __future__ import annotations

from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

from garmin_sync.zepp_activity_provider import ZeppActivityProvider


RAW_RUN = {
    "trackid": "track-42",
    "source": "run.watch.helio.zepp.com",
    "sport_title": "Correr al aire libre",
    "sport_mode": 7,
    "end_time": "1790229960",
    "run_time": "2518",
    "dis": "8020",
    "avg_heart_rate": "151",
    "max_heart_rate": 174,
    "calorie": "613",
    "altitude_ascend": 88,
    "exercise_load": 92,
}

RAW_STRENGTH = {
    "trackid": "strength-52",
    "source": "run.zepp.com",
    "sport_title": "",
    "sport_mode": 0,
    "type": 52,
    "strength_training_group": '[{"actionType": 0, "count": 10}]',
    "end_time": "2026-09-28T19:18:00+02:00",
    "run_time": "3182",
    "dis": "0.0",
    "avg_heart_rate": "118",
    "max_heart_rate": 142,
    "calorie": "286",
    "exercise_load": 51,
}


def response(payload: dict, status_code: int = 200) -> Mock:
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    return result


class ZeppActivityProviderTests(TestCase):
    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_normalizes_zero_distance_strength_session_without_pace(self, get: Mock) -> None:
        get.return_value = response({"code": 1, "data": {"summary": [RAW_STRENGTH]}})

        activities, status = ZeppActivityProvider("secret", "42").fetch_activities(date(2026, 9, 28), date(2026, 9, 28))

        self.assertEqual(status, {"status": "ok", "records_received": 1})
        self.assertEqual(activities[0]["name"], "Entrenamiento de fuerza")
        self.assertEqual(activities[0]["sport"], "strength")
        self.assertEqual(activities[0]["km"], 0.0)
        self.assertEqual(activities[0]["duration_s"], 3182)
        self.assertNotIn("pace", activities[0])
        self.assertNotIn("avg_speed_kmh", activities[0])

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_fetch_activities_uses_web_headers_and_normalizes_a_run(self, get: Mock) -> None:
        get.return_value = response({"code": 1, "data": {"summary": [RAW_RUN]}})
        provider = ZeppActivityProvider("secret", "42", "https://example.test", "Europe/Madrid")

        activities, status = provider.fetch_activities(date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(activities[0]["id"], "zepp:run.watch.helio.zepp.com:track-42")
        self.assertEqual(activities[0]["source"], "zepp")
        self.assertEqual(activities[0]["source_activity_id"], "track-42")
        self.assertEqual(activities[0]["sport"], "running")
        self.assertEqual(activities[0]["km"], 8.02)
        self.assertEqual(activities[0]["duration_s"], 2518)
        self.assertEqual(activities[0]["provider_exercise_load"], {"value": 92, "source": "zepp"})
        self.assertEqual(status, {"status": "ok", "records_received": 1})
        self.assertEqual(
            get.call_args.kwargs["headers"],
            {"apptoken": "secret", "appPlatform": "web", "appname": "com.xiaomi.hm.health"},
        )

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_empty_zepp_history_is_a_success_with_no_activities(self, get: Mock) -> None:
        get.return_value = response({"code": 1, "data": {"summary": []}})

        activities, status = ZeppActivityProvider("secret", "42").fetch_activities(date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(activities, [])
        self.assertEqual(status, {"status": "ok", "records_received": 0})

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_missing_credentials_disable_without_request(self, get: Mock) -> None:
        activities, status = ZeppActivityProvider("", "").fetch_activities(date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(activities, [])
        self.assertEqual(status, {"status": "disabled", "records_received": 0})
        get.assert_not_called()

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_auth_error_is_redacted(self, get: Mock) -> None:
        get.return_value = response({}, status_code=401)

        _activities, status = ZeppActivityProvider("secret-token", "42").fetch_activities(date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(status["status"], "auth_error")
        self.assertNotIn("secret-token", repr(status))

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_invalid_payload_and_invalid_record_are_safe(self, get: Mock) -> None:
        get.return_value = response({"code": 0, "data": {"summary": []}})
        _activities, invalid_status = ZeppActivityProvider("secret", "42").fetch_activities(date(2026, 9, 24), date(2026, 9, 24))
        self.assertEqual(invalid_status["status"], "invalid_data")

        invalid_run = {**RAW_RUN, "run_time": "0"}
        get.return_value = response({"code": 1, "data": {"summary": [invalid_run]}})
        activities, status = ZeppActivityProvider("secret", "42").fetch_activities(date(2026, 9, 24), date(2026, 9, 24))
        self.assertEqual(activities, [])
        self.assertEqual(status, {"status": "ok", "records_received": 0})

    @patch("garmin_sync.zepp_activity_provider.requests.get")
    def test_accepts_seconds_milliseconds_and_iso_end_timestamps(self, get: Mock) -> None:
        milliseconds = {**RAW_RUN, "trackid": "milliseconds", "end_time": str(1790229960 * 1000)}
        iso = {**RAW_RUN, "trackid": "iso", "end_time": "2026-09-24T08:06:00+02:00"}
        get.return_value = response({"code": 1, "data": {"summary": [RAW_RUN, milliseconds, iso]}})

        activities, _status = ZeppActivityProvider("secret", "42", timezone_name="Europe/Madrid").fetch_activities(
            date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertEqual(len(activities), 3)
        self.assertTrue(all(item["date"] == "2026-09-24" for item in activities))


if __name__ == "__main__":
    __import__("unittest").main()
