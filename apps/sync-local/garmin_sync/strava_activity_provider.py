from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


STRAVA_API_URL = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


class StravaTokenStore:
    """Persist Strava's rotating OAuth tokens outside the repository."""

    def __init__(self, path: Path, environment: Mapping[str, str] | None = None) -> None:
        self._path = path.expanduser()
        self._environment = environment if environment is not None else os.environ

    def load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                value = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                value = None
            if isinstance(value, dict):
                return value
        return {
            "access_token": self._environment.get("STRAVA_TOKEN_ACCESS", ""),
            "refresh_token": self._environment.get("STRAVA_TOKEN_UPDATED", ""),
            "expires_at": _integer(self._environment.get("STRAVA_TOKEN_EXPIRES_AT")),
        }

    def save(self, access_token: str, refresh_token: str, expires_at: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.chmod(0o600)
        temporary.replace(self._path)
        self._path.chmod(0o600)


class StravaActivityProvider:
    """Read recent Strava activities and normalize them for Garmin Coach."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_store: StravaTokenStore,
        timezone_name: str = "Europe/Madrid",
        api_url: str = STRAVA_API_URL,
        token_url: str = STRAVA_TOKEN_URL,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_store = token_store
        self._timezone = ZoneInfo(timezone_name)
        self._api_url = api_url.rstrip("/")
        self._token_url = token_url

    def fetch_activities(self, start_day: date, end_day: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        credentials = self._token_store.load()
        refresh_token = _text(credentials.get("refresh_token"))
        if not self._client_id or not self._client_secret or not refresh_token:
            return [], _status("disabled")
        try:
            access_token = self._access_token(credentials, refresh_token)
            records = self._activity_records(access_token, start_day, end_day)
        except _StravaError as exc:
            return [], _status(exc.status)

        activities = [
            activity
            for activity in (_normalize_record(record, self._timezone) for record in records)
            if activity and start_day <= date.fromisoformat(activity["date"]) <= end_day
        ]
        activities.sort(key=lambda item: (item["started_at"], item["id"]))
        return activities, {"status": "ok", "records_received": len(activities)}

    def _access_token(self, credentials: dict[str, Any], refresh_token: str) -> str:
        access_token = _text(credentials.get("access_token"))
        expires_at = _integer(credentials.get("expires_at")) or 0
        if access_token and expires_at > int(time.time()) + 3600:
            return access_token
        try:
            response = requests.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise _StravaError("network_error") from exc
        if response.status_code in {400, 401, 403}:
            raise _StravaError("auth_error")
        if response.status_code != 200:
            raise _StravaError("api_error")
        try:
            payload = response.json()
        except ValueError as exc:
            raise _StravaError("invalid_data") from exc
        if not isinstance(payload, dict):
            raise _StravaError("invalid_data")
        access_token = _text(payload.get("access_token"))
        next_refresh_token = _text(payload.get("refresh_token"))
        expires_at = _integer(payload.get("expires_at"))
        if not access_token or not next_refresh_token or expires_at is None:
            raise _StravaError("invalid_data")
        self._token_store.save(access_token, next_refresh_token, expires_at)
        return access_token

    def _activity_records(self, access_token: str, start_day: date, end_day: date) -> list[dict[str, Any]]:
        start = datetime.combine(start_day, datetime_time.min, tzinfo=self._timezone)
        end = datetime.combine(end_day + timedelta(days=1), datetime_time.min, tzinfo=self._timezone)
        records: list[dict[str, Any]] = []
        for page in range(1, 11):
            try:
                response = requests.get(
                    f"{self._api_url}/athlete/activities",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "after": int(start.timestamp()) - 1,
                        "before": int(end.timestamp()),
                        "page": page,
                        "per_page": 100,
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise _StravaError("network_error") from exc
            if response.status_code in {401, 403}:
                raise _StravaError("auth_error")
            if response.status_code != 200:
                raise _StravaError("api_error")
            try:
                payload = response.json()
            except ValueError as exc:
                raise _StravaError("invalid_data") from exc
            if not isinstance(payload, list):
                raise _StravaError("invalid_data")
            page_records = [item for item in payload if isinstance(item, dict)]
            records.extend(page_records)
            if len(payload) < 100:
                break
        return records


class _StravaError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _normalize_record(record: dict[str, Any], local_timezone: ZoneInfo) -> dict[str, Any] | None:
    activity_id = _text(record.get("id"))
    started_at = _timestamp(record.get("start_date"), local_timezone)
    duration_s = _positive_number(record.get("elapsed_time")) or _positive_number(record.get("moving_time"))
    distance_m = _nonnegative_number(record.get("distance"))
    sport_type = _text(record.get("sport_type") or record.get("type"))
    normalized_sport = _sport(sport_type)
    if (
        not activity_id
        or started_at is None
        or duration_s is None
        or distance_m is None
        or (distance_m == 0 and normalized_sport != "strength")
    ):
        return None

    distance_km = round(distance_m / 1000, 2)
    activity: dict[str, Any] = {
        "id": f"strava:{activity_id}",
        "source": "strava",
        "source_activity_id": activity_id,
        "date": started_at.date().isoformat(),
        "started_at": started_at.isoformat(),
        "name": _text(record.get("name")) or "Actividad Strava",
        "sport": normalized_sport,
        "type": sport_type or "Workout",
        "km": distance_km,
        "duration_s": round(duration_s),
        "hours": round(duration_s / 3600, 2),
    }
    source_device = _text(record.get("device_name"))
    if source_device:
        activity["source_device"] = source_device
    if distance_km > 0:
        activity["pace"] = _pace(distance_km, duration_s)
        activity["avg_speed_kmh"] = round(distance_km / (duration_s / 3600), 1)
    for output, raw_key in {
        "avg_hr": "average_heartrate",
        "max_hr": "max_heartrate",
        "elevation_gain_m": "total_elevation_gain",
        "calories": "calories",
    }.items():
        value = _positive_number(record.get(raw_key))
        if value is not None:
            activity[output] = round(value) if output != "calories" else round(value, 1)
    return activity


def _timestamp(value: Any, local_timezone: ZoneInfo) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(local_timezone)


def _sport(value: str) -> str:
    lowered = value.lower()
    if "run" in lowered:
        return "running"
    if any(token in lowered for token in ("ride", "cycling", "bike")):
        return "cycling"
    if any(token in lowered for token in ("weight", "crossfit", "strength")):
        return "strength"
    return "other"


def _pace(distance_km: float, duration_s: float) -> str:
    minutes, seconds = divmod(round(duration_s / distance_km), 60)
    return f"{minutes}:{seconds:02d}/km"


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _nonnegative_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _status(value: str) -> dict[str, Any]:
    return {"status": value, "records_received": 0}
