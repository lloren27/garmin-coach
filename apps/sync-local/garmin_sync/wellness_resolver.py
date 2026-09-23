from __future__ import annotations

from datetime import datetime
from typing import Any


EFFECTIVE_SOURCE_POLICY: dict[str, tuple[str, ...]] = {
    "sleep": ("zepp", "garmin"),
    "resting_hr": ("zepp", "garmin"),
    "steps": ("zepp", "garmin"),
    "stress": ("zepp",),
    "atl": ("zepp",),
    "ctl": ("zepp",),
    "tsb": ("zepp",),
    "trimp": ("zepp",),
    "sport_load": ("zepp",),
    "recovery_factor": ("zepp",),
    "vo2max": ("garmin",),
}


def resolve_wellness(
    garmin: dict[str, Any] | None,
    zepp: dict[str, Any] | None,
    wellness_date: str,
) -> dict[str, Any]:
    providers = {"garmin": garmin or {}, "zepp": zepp or {}}
    resolved: dict[str, Any] = {"date": wellness_date}
    for metric, sources in EFFECTIVE_SOURCE_POLICY.items():
        for source in sources:
            candidate = _candidate_for(metric, providers[source])
            if is_valid_metric(metric, candidate):
                resolved[metric] = _with_source(candidate, source)
                break
    return resolved


def is_valid_metric(name: str, candidate: Any) -> bool:
    if name == "sleep":
        return _valid_sleep(candidate)
    if name == "resting_hr":
        value = _metric_value(candidate)
        return _is_number(value) and 20 <= value <= 250
    if name == "steps":
        value = _metric_value(candidate)
        return _is_number(value) and value >= 0
    if name == "stress":
        return isinstance(candidate, dict) and _is_number(candidate.get("avg"))
    if name in {"atl", "ctl", "tsb"}:
        return _is_number(_metric_value(candidate))
    if name in {"trimp", "recovery_factor"}:
        value = _metric_value(candidate)
        return _is_number(value) and value >= 0
    if name == "sport_load":
        value = _metric_value(candidate)
        return _is_number(value) and value >= 0
    if name == "vo2max":
        value = _metric_value(candidate)
        return _is_number(value) and value > 0
    return False


def _candidate_for(metric: str, provider: dict[str, Any]) -> Any:
    if metric in {"atl", "ctl", "tsb", "recovery_factor"}:
        if metric in provider:
            return provider[metric]
        training_load = provider.get("training_load")
        if isinstance(training_load, dict) and metric in training_load:
            return {
                "value": training_load[metric],
                "observed_at": training_load.get("observed_at"),
            }
        return None
    return provider.get(metric)


def _with_source(candidate: Any, source: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {"value": candidate, "source": source}
    return {key: value for key, value in {**candidate, "source": source}.items() if value is not None}


def _valid_sleep(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    total = candidate.get("total_minutes")
    start = candidate.get("start")
    end = candidate.get("end")
    if not (_is_number(total) and total > 0 and isinstance(start, str) and isinstance(end, str)):
        return False
    try:
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return False
    if start_time.tzinfo is None or end_time.tzinfo is None or end_time <= start_time:
        return False
    stage_total = 0
    for field in ("deep_minutes", "light_minutes", "rem_minutes", "awake_minutes"):
        value = candidate.get(field)
        if value is not None:
            if not (_is_number(value) and value >= 0):
                return False
            stage_total += value
    return stage_total == 0 or stage_total <= total


def _metric_value(candidate: Any) -> Any:
    return candidate.get("value") if isinstance(candidate, dict) else candidate


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
