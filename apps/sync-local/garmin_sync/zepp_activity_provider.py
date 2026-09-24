from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests


class ZeppActivityProvider:
    """Read and normalize recent workouts from the Zepp web history endpoint."""

    WEB_HEADERS = {"appPlatform": "web", "appname": "com.xiaomi.hm.health"}

    def __init__(
        self,
        token: str,
        user_id: str,
        base_url: str | None = None,
        timezone_name: str = "Europe/Madrid",
    ) -> None:
        self._token = token
        self._user_id = user_id
        self._base_url = (base_url or "https://api-mifit-us2.zepp.com").rstrip("/")
        self._timezone = ZoneInfo(timezone_name)

    def fetch_activities(self, start_day: date, end_day: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self._token or not self._user_id:
            return [], {"status": "disabled", "records_received": 0}
        try:
            records = _history_records(self._get("/v1/sport/run/history.json", {"userid": self._user_id}))
        except _ZeppActivityError as exc:
            return [], {"status": exc.status, "records_received": 0}

        activities = [activity for activity in (_normalize_record(record, self._timezone) for record in records) if activity]
        activities = [activity for activity in activities if start_day <= date.fromisoformat(activity["date"]) <= end_day]
        return sorted(activities, key=lambda activity: (activity["started_at"], activity["id"])), {
            "status": "ok",
            "records_received": len(activities),
        }

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        headers = {"apptoken": self._token, **self.WEB_HEADERS}
        try:
            response = requests.get(f"{self._base_url}{path}", headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            raise _ZeppActivityError("network_error") from exc
        if response.status_code == 401:
            raise _ZeppActivityError("auth_error")
        if response.status_code != 200:
            raise _ZeppActivityError("api_error")
        try:
            value = response.json()
        except ValueError as exc:
            raise _ZeppActivityError("invalid_data") from exc
        if not isinstance(value, dict):
            raise _ZeppActivityError("invalid_data")
        return value


class _ZeppActivityError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _history_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    records = data.get("summary") if isinstance(data, dict) else None
    if payload.get("code") != 1 or not isinstance(records, list):
        raise _ZeppActivityError("invalid_data")
    return [record for record in records if isinstance(record, dict)]


def _normalize_record(record: dict[str, Any], local_timezone: ZoneInfo) -> dict[str, Any] | None:
    track_id = _text(record.get("trackid"))
    source_id = _text(record.get("source"))
    duration_s = _positive_number(record.get("run_time"))
    distance_m = _positive_number(record.get("dis"))
    ended_at = _timestamp(record.get("end_time"), local_timezone)
    if not track_id or not source_id or duration_s is None or distance_m is None or ended_at is None:
        return None

    started_at = ended_at.timestamp() - duration_s
    start = datetime.fromtimestamp(started_at, tz=local_timezone)
    distance_km = round(distance_m / 1000, 2)
    if distance_km <= 0:
        return None

    title = _text(record.get("sport_title")) or "Actividad Zepp"
    activity: dict[str, Any] = {
        "id": f"zepp:{source_id}:{track_id}",
        "source": "zepp",
        "source_activity_id": track_id,
        "date": start.date().isoformat(),
        "started_at": start.isoformat(),
        "name": title,
        "sport": _sport(title),
        "type": _text(record.get("sport_mode")) or "other",
        "km": distance_km,
        "duration_s": round(duration_s),
        "hours": round(duration_s / 3600, 2),
        "pace": _pace(distance_km, duration_s),
        "avg_speed_kmh": round(distance_km / (duration_s / 3600), 1),
    }
    for output, raw_key in {
        "avg_hr": "avg_heart_rate",
        "max_hr": "max_heart_rate",
        "calories": "calorie",
        "elevation_gain_m": "altitude_ascend",
    }.items():
        value = _positive_number(record.get(raw_key))
        if value is not None:
            activity[output] = round(value) if output != "calories" else round(value, 1)
    exercise_load = _nonnegative_number(record.get("exercise_load"))
    if exercise_load is not None:
        activity["provider_exercise_load"] = {"value": exercise_load, "source": "zepp"}
    return activity


def _timestamp(value: Any, local_timezone: ZoneInfo) -> datetime | None:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().replace(".", "", 1).isdigit()):
        try:
            seconds = float(value)
            if seconds > 100_000_000_000:
                seconds /= 1000
            return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(local_timezone)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(local_timezone)


def _sport(title: str) -> str:
    lowered = title.lower()
    if any(token in lowered for token in ("run", "correr", "carrera")):
        return "running"
    if any(token in lowered for token in ("bike", "bici", "cicl")):
        return "cycling"
    if "fuerza" in lowered or "strength" in lowered:
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


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""
