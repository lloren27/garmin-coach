from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from garmin_sync.strava_activity_provider import StravaActivityProvider, StravaTokenStore


RAW_RUN = {
    "id": 123456,
    "external_id": "cmf-run-42.fit",
    "name": "Morning Run",
    "sport_type": "Run",
    "start_date": "2026-08-24T05:25:00Z",
    "start_date_local": "2026-08-24T07:25:00Z",
    "distance": 8020.0,
    "moving_time": 2450,
    "elapsed_time": 2518,
    "total_elevation_gain": 88.0,
    "average_heartrate": 151.2,
    "max_heartrate": 174.0,
    "device_name": "CMF Watch 3 Pro",
}


def response(payload: object, status_code: int = 200) -> Mock:
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    return result


class StravaActivityProviderTests(TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.token_file = Path(self.tempdir.name) / "strava-tokens.json"
        self.store = StravaTokenStore(
            self.token_file,
            {
                "STRAVA_TOKEN_ACCESS": "old-access",
                "STRAVA_TOKEN_UPDATED": "old-refresh",
            },
        )

    @patch("garmin_sync.strava_activity_provider.requests.get")
    @patch("garmin_sync.strava_activity_provider.requests.post")
    def test_refreshes_token_and_normalizes_cmf_run(self, post: Mock, get: Mock) -> None:
        post.return_value = response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": 2_000_000_000,
            }
        )
        get.return_value = response([RAW_RUN])
        provider = StravaActivityProvider(
            "client-id",
            "client-secret",
            self.store,
            timezone_name="Europe/Madrid",
        )

        activities, status = provider.fetch_activities(date(2026, 8, 24), date(2026, 8, 24))

        self.assertEqual(status, {"status": "ok", "records_received": 1})
        self.assertEqual(
            activities[0],
            {
                "id": "strava:123456",
                "source": "strava",
                "source_activity_id": "123456",
                "source_device": "CMF Watch 3 Pro",
                "date": "2026-08-24",
                "started_at": "2026-08-24T07:25:00+02:00",
                "name": "Morning Run",
                "sport": "running",
                "type": "Run",
                "km": 8.02,
                "duration_s": 2518,
                "hours": 0.7,
                "pace": "5:14/km",
                "avg_speed_kmh": 11.5,
                "avg_hr": 151,
                "max_hr": 174,
                "elevation_gain_m": 88,
            },
        )
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer new-access"})
        saved = json.loads(self.token_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], "new-refresh")
        self.assertEqual(self.token_file.stat().st_mode & 0o777, 0o600)

    @patch("garmin_sync.strava_activity_provider.requests.get")
    @patch("garmin_sync.strava_activity_provider.requests.post")
    def test_missing_credentials_disables_without_network_calls(self, post: Mock, get: Mock) -> None:
        provider = StravaActivityProvider("", "", StravaTokenStore(self.token_file, {}))

        activities, status = provider.fetch_activities(date(2026, 8, 24), date(2026, 8, 24))

        self.assertEqual(activities, [])
        self.assertEqual(status, {"status": "disabled", "records_received": 0})
        post.assert_not_called()
        get.assert_not_called()

    @patch("garmin_sync.strava_activity_provider.requests.get")
    @patch("garmin_sync.strava_activity_provider.requests.post")
    def test_activity_permission_error_is_redacted(self, post: Mock, get: Mock) -> None:
        post.return_value = response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": 2_000_000_000,
            }
        )
        get.return_value = response(
            {
                "message": "Authorization Error",
                "errors": [
                    {"resource": "AccessToken", "field": "activity:read_permission", "code": "missing"}
                ],
            },
            status_code=401,
        )
        provider = StravaActivityProvider("client-id", "client-secret", self.store)

        activities, status = provider.fetch_activities(date(2026, 8, 24), date(2026, 8, 24))

        self.assertEqual(activities, [])
        self.assertEqual(status, {"status": "auth_error", "records_received": 0})
        self.assertNotIn("new-access", repr(status))
        self.assertNotIn("new-refresh", repr(status))


if __name__ == "__main__":
    __import__("unittest").main()
