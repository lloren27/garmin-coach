from __future__ import annotations

from datetime import datetime
from typing import Any


def merge_activities(garmin: list[dict[str, Any]], zepp: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine normalized provider records, preserving Garmin for proven duplicates."""

    unique_garmin = _unique_by_id(garmin)
    kept_zepp = [item for item in _unique_by_id(zepp) if not any(_is_duplicate(garmin_item, item) for garmin_item in unique_garmin)]
    return sorted(unique_garmin + kept_zepp, key=lambda item: (str(item.get("started_at") or item.get("date") or ""), str(item.get("id") or "")))


def _unique_by_id(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for activity in activities:
        activity_id = str(activity.get("id") or "")
        if not activity_id or activity_id in seen:
            continue
        seen.add(activity_id)
        unique.append(activity)
    return unique


def _is_duplicate(garmin: dict[str, Any], zepp: dict[str, Any]) -> bool:
    return (
        garmin.get("sport") == zepp.get("sport")
        and _start_difference_seconds(garmin, zepp) < 600
        and _overlap_fraction(garmin, zepp) >= 0.70
        and _distance_matches_when_available(garmin, zepp)
    )


def _start_difference_seconds(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = _started_at(left)
    right_start = _started_at(right)
    if left_start is None or right_start is None:
        return float("inf")
    return abs((left_start - right_start).total_seconds())


def _overlap_fraction(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = _started_at(left)
    right_start = _started_at(right)
    left_duration = _positive_number(left.get("duration_s"))
    right_duration = _positive_number(right.get("duration_s"))
    if left_start is None or right_start is None or left_duration is None or right_duration is None:
        return 0.0
    left_end = left_start.timestamp() + left_duration
    right_end = right_start.timestamp() + right_duration
    overlap = max(0.0, min(left_end, right_end) - max(left_start.timestamp(), right_start.timestamp()))
    return overlap / min(left_duration, right_duration)


def _distance_matches_when_available(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_km = _positive_number(left.get("km"))
    right_km = _positive_number(right.get("km"))
    if left_km is None or right_km is None:
        return True
    return abs(left_km - right_km) / max(left_km, right_km) <= 0.10


def _started_at(activity: dict[str, Any]) -> datetime | None:
    value = activity.get("started_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
