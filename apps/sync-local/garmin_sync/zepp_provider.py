from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import requests

from .wellness_models import NormalizedSleep, NormalizedWellness, ProviderDayResult, ProviderStatus

try:
    from zepp_export import ZeppAPIError, ZeppAuthError, ZeppClient
except ImportError:
    class ZeppAuthError(Exception):
        pass

    class ZeppAPIError(Exception):
        pass

    ZeppClient = None


class ZeppProvider:
    def __init__(
        self,
        token: str,
        user_id: str,
        base_url: str | None = None,
        timezone_name: str = "Europe/Madrid",
    ) -> None:
        self._token = token
        self._user_id = user_id
        self._base_url = base_url
        self._timezone = ZoneInfo(timezone_name)
        self._client: Any | None = None

    def fetch_days(self, dates: list[date]) -> tuple[dict[str, ProviderDayResult], dict[str, Any]]:
        requested = len(dates)
        if not self._token or not self._user_id:
            return {}, self._status(ProviderStatus.DISABLED, requested, 0)
        try:
            client = self._get_client()
        except Exception as exc:
            return {}, self._status(self._error_status(exc), requested, 0)

        results = {day.isoformat(): self._fetch_day(client, day) for day in dates}
        received = sum(result.status == "ok" for result in results.values())
        statuses = {result.error_kind for result in results.values() if result.error_kind}
        if received == requested:
            status = ProviderStatus.OK
        elif received:
            status = ProviderStatus.PARTIAL
        elif ProviderStatus.AUTH_ERROR.value in statuses:
            status = ProviderStatus.AUTH_ERROR
        elif ProviderStatus.NETWORK_ERROR.value in statuses:
            status = ProviderStatus.NETWORK_ERROR
        elif ProviderStatus.API_ERROR.value in statuses:
            status = ProviderStatus.API_ERROR
        else:
            status = ProviderStatus.INVALID_DATA
        return results, self._status(status, requested, received)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if ZeppClient is None:
            raise RuntimeError("zepp-export is not installed")
        options: dict[str, Any] = {"token": self._token, "user_id": self._user_id}
        if self._base_url:
            options["base_url"] = self._base_url
        self._client = ZeppClient(**options)
        return self._client

    def _fetch_day(self, client: Any, day: date) -> ProviderDayResult:
        day_text = day.isoformat()
        try:
            sleep = self._normalize_sleep(client.get_sleep(day_text))
            if not _is_valid_sleep(sleep):
                sleep = self._sleep_from_band_data(client, day)
            steps = self._normalize_steps(client.get_steps(day_text), day_text)
            stress = self._normalize_stress(client.get_stress(day_text, day_text), day_text)
            training_load = self._normalize_training_load(client.get_training_load(day_text, day_text), day_text)
            trimp = self._normalize_value(client.get_phn(day_text, day_text), day_text, ("trimp", "value"), "trimp")
            sport_load = self._normalize_value(client.get_sport_load(day_text, day_text), day_text, ("daily_load", "sport_load", "load", "value"), "sport_load")
            vo2max = self._normalize_vo2max(client.get_vo2_max(day_text, day_text), day_text)
            resting_hr = None
            if sleep and sleep.resting_hr is not None:
                resting_hr = {"value": sleep.resting_hr, "unit": "bpm", "source": "zepp", "observed_at": day_text}
            return ProviderDayResult(
                date=day_text,
                status="ok",
                data=NormalizedWellness(
                    sleep=sleep,
                    resting_hr=resting_hr,
                    steps=steps,
                    stress=stress,
                    training_load=training_load,
                    trimp=trimp,
                    sport_load=sport_load,
                    vo2max_observations=vo2max,
                ),
            )
        except Exception as exc:
            return ProviderDayResult(date=day_text, status="error", error_kind=self._error_status(exc).value)

    def _status(self, status: ProviderStatus, requested: int, received: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status.value,
            "days_requested": requested,
            "days_received": received,
        }
        if received:
            payload["last_success_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        return payload

    @staticmethod
    def _error_status(exc: Exception) -> ProviderStatus:
        if isinstance(exc, ZeppAuthError):
            return ProviderStatus.AUTH_ERROR
        if isinstance(exc, ZeppAPIError) and isinstance(exc.__cause__, requests.RequestException):
            return ProviderStatus.NETWORK_ERROR
        if isinstance(exc, httpx.NetworkError):
            return ProviderStatus.NETWORK_ERROR
        if isinstance(exc, (ZeppAPIError, httpx.HTTPStatusError)):
            return ProviderStatus.API_ERROR
        return ProviderStatus.INVALID_DATA

    def _normalize_sleep(self, value: Any) -> NormalizedSleep | None:
        if not isinstance(value, dict):
            return None
        start = value.get("start") or value.get("start_time") or value.get("sleep_start")
        end = value.get("end") or value.get("end_time") or value.get("sleep_end")
        total = value.get("total_minutes") if "total_minutes" in value else value.get("duration_minutes")
        if total is None:
            total = value.get("sleep_minutes")
        if not isinstance(start, str) or not isinstance(end, str) or not isinstance(total, (int, float)):
            return None
        stage_minutes = _stage_minutes(value.get("stages"))
        return NormalizedSleep(
            source_id=_string(value.get("id") or value.get("sleep_id")),
            start=self._offset_timestamp(start),
            end=self._offset_timestamp(end),
            total_minutes=round(total),
            deep_minutes=_integer(value.get("deep_minutes")),
            light_minutes=_integer(value.get("light_minutes")),
            rem_minutes=_integer(value.get("rem_minutes")) or stage_minutes.get("rem"),
            awake_minutes=_integer(value.get("awake_minutes")) or stage_minutes.get("awake"),
            score=_integer(value.get("sleep_score") or value.get("score")),
            resting_hr=_integer(value.get("resting_hr")),
        )

    def _offset_timestamp(self, timestamp: str) -> str:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._timezone)
        return parsed.astimezone(self._timezone).isoformat()

    @staticmethod
    def _normalize_steps(value: Any, day: str) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        steps = value.get("steps") if "steps" in value else value.get("total_steps")
        if not isinstance(steps, (int, float)):
            return None
        return {"value": round(steps), "unit": "steps", "source": "zepp", "observed_at": day}

    def _normalize_stress(self, value: Any, day: str) -> dict[str, Any] | None:
        record = self._daily_record(value, day)
        if not record:
            return None
        average = _first_number(record, ("avg_stress", "average", "avg"))
        if average is None:
            return None
        result: dict[str, Any] = {"avg": average, "source": "zepp", "observed_at": day}
        for output, keys in {
            "min": ("min_stress", "min"),
            "max": ("max_stress", "max"),
            "sample_count": ("sample_count", "samples"),
            "coverage_minutes": ("coverage_minutes",),
        }.items():
            found = _first_number(record, keys)
            if found is not None:
                result[output] = round(found)
        readings = record.get("readings")
        if isinstance(readings, list):
            result["sample_count"] = len(readings)
            result["coverage_minutes"] = len(readings) * 5
        zones = record.get("zone_percentages")
        if isinstance(zones, dict) and result.get("coverage_minutes"):
            coverage = result["coverage_minutes"]
            result["zones"] = {
                f"{zone}_minutes": round(coverage * percentage / 100)
                for zone, percentage in zones.items()
                if zone in {"low", "medium", "high"} and _number(percentage) is not None
            }
        return result

    def _normalize_training_load(self, value: Any, day: str) -> dict[str, Any] | None:
        record = self._daily_record(value, day)
        if not record:
            return None
        result = {key: _number(record.get(key)) for key in ("atl", "ctl", "tsb", "recovery_factor")}
        result = {key: item for key, item in result.items() if item is not None}
        if not result:
            return None
        return {**result, "source": "zepp", "observed_at": day}

    def _normalize_value(self, value: Any, day: str, keys: tuple[str, ...], field_name: str) -> dict[str, Any] | None:
        record = self._daily_record(value, day)
        number = _first_number(record, keys) if record else None
        if number is None:
            return None
        return {"value": number, "source": "zepp", "observed_at": day, "metric": field_name}

    def _normalize_vo2max(self, value: Any, day: str) -> list[dict[str, Any]]:
        items = value if isinstance(value, list) else [value]
        observations = []
        for item in items:
            if not isinstance(item, dict):
                continue
            observed_at = str(item.get("date") or item.get("observed_at") or day)
            measurement = _first_number(item, ("vo2_max", "vo2max", "value"))
            if measurement is not None:
                observations.append({"value": measurement, "unit": "ml/kg/min", "source": "zepp", "observed_at": observed_at})
        return observations

    def _sleep_from_band_data(self, client: Any, day: date) -> NormalizedSleep | None:
        fetch_band_data = getattr(client, "get_band_data", None)
        if not callable(fetch_band_data):
            return None
        for source_day in (day - timedelta(days=1), day):
            band = fetch_band_data(source_day.isoformat())
            summary = band.get("summary") if isinstance(band, dict) else None
            record = summary.get("slp") if isinstance(summary, dict) else None
            if not isinstance(record, dict):
                continue
            start = _number(record.get("st"))
            end = _number(record.get("ed"))
            if start is None or end is None or end <= start:
                continue
            start_at = datetime.fromtimestamp(start, self._timezone)
            end_at = datetime.fromtimestamp(end, self._timezone)
            if end_at.date() != day:
                continue
            stages = record.get("stage") if isinstance(record.get("stage"), list) else []
            stage_minutes = {"deep": 0, "light": 0, "rem": 0, "awake": 0}
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                name = {4: "light", 5: "deep", 7: "awake", 8: "rem"}.get(stage.get("mode"))
                start_minute = _number(stage.get("start"))
                end_minute = _number(stage.get("stop"))
                if name and start_minute is not None and end_minute is not None and end_minute >= start_minute:
                    stage_minutes[name] += round(end_minute - start_minute)
            sleep = NormalizedSleep(
                start=start_at.isoformat(),
                end=end_at.isoformat(),
                total_minutes=round((end_at - start_at).total_seconds() / 60),
                deep_minutes=stage_minutes["deep"] or _integer(record.get("dp")),
                light_minutes=stage_minutes["light"] or _integer(record.get("lt")),
                rem_minutes=stage_minutes["rem"] or None,
                awake_minutes=stage_minutes["awake"] or None,
                score=_integer(record.get("ss")),
                resting_hr=_integer(record.get("rhr")),
            )
            if _is_valid_sleep(sleep):
                return sleep
        return None

    def _daily_record(self, value: Any, day: str) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and self._record_date(item) == day:
                    return item
            return next((item for item in value if isinstance(item, dict)), None)
        return None

    def _record_date(self, item: dict[str, Any]) -> str | None:
        direct = item.get("date") or item.get("day")
        if direct is not None:
            return str(direct)[:10]
        timestamp = item.get("timestamp")
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(self._timezone).date().isoformat()
            except ValueError:
                return timestamp[:10] if len(timestamp) >= 10 else None
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            seconds = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
            return datetime.fromtimestamp(seconds, self._timezone).date().isoformat()
        return None


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return round(number) if number is not None else None


def _stage_minutes(value: Any) -> dict[str, int]:
    totals: dict[str, int] = {}
    if not isinstance(value, list):
        return totals
    for stage in value:
        if not isinstance(stage, dict):
            continue
        name = stage.get("stage")
        minutes = _integer(stage.get("duration_minutes"))
        if isinstance(name, str) and minutes is not None:
            totals[name] = totals.get(name, 0) + minutes
    return totals


def _first_number(value: dict[str, Any] | None, keys: tuple[str, ...]) -> float | int | None:
    if not value:
        return None
    for key in keys:
        number = _number(value.get(key))
        if number is not None:
            return number
    return None


def _string(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _is_valid_sleep(value: NormalizedSleep | None) -> bool:
    if value is None or value.total_minutes <= 0:
        return False
    try:
        return datetime.fromisoformat(value.end) > datetime.fromisoformat(value.start)
    except ValueError:
        return False
