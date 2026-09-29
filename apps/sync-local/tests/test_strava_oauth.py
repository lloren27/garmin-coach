from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest import TestCase
from unittest.mock import Mock, patch

from garmin_sync.strava_activity_provider import StravaTokenStore
from garmin_sync.strava_oauth import authorization_url, callback_code, exchange_authorization_code


def response(payload: object, status_code: int = 200) -> Mock:
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    return result


class StravaOAuthTests(TestCase):
    def test_authorization_url_requests_private_activity_read_scope(self) -> None:
        url = authorization_url("159898", "http://localhost:8765/strava/callback", "safe-state")
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["client_id"], ["159898"])
        self.assertEqual(query["redirect_uri"], ["http://localhost:8765/strava/callback"])
        self.assertEqual(query["scope"], ["read,activity:read_all"])
        self.assertEqual(query["state"], ["safe-state"])
        self.assertEqual(query["approval_prompt"], ["force"])

    def test_callback_rejects_wrong_state_and_returns_authorization_code(self) -> None:
        valid = callback_code("/strava/callback?state=safe-state&code=one-time", "safe-state")
        invalid = callback_code("/strava/callback?state=other&code=stolen", "safe-state")

        self.assertEqual(valid, "one-time")
        self.assertIsNone(invalid)

    @patch("garmin_sync.strava_oauth.requests.post")
    def test_exchange_saves_rotating_tokens_without_returning_them(self, post: Mock) -> None:
        post.return_value = response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": 2_000_000_000,
                "athlete": {"id": 42},
            }
        )
        with tempfile.TemporaryDirectory() as tempdir:
            token_file = Path(tempdir) / "strava.json"
            result = exchange_authorization_code(
                client_id="159898",
                client_secret="client-secret",
                code="one-time",
                redirect_uri="http://localhost:8765/strava/callback",
                token_store=StravaTokenStore(token_file, {}),
            )

            self.assertEqual(result, {"ok": True, "athlete_id": "42"})
            self.assertEqual(json.loads(token_file.read_text())["refresh_token"], "new-refresh")
            self.assertNotIn("new-access", repr(result))
            self.assertNotIn("new-refresh", repr(result))
            self.assertEqual(post.call_args.kwargs["data"]["code"], "one-time")


if __name__ == "__main__":
    __import__("unittest").main()
