from __future__ import annotations

from datetime import datetime
from copy import deepcopy
import math
from typing import Any


def merge_activities(
    garmin: list[dict[str, Any]],
    zepp: list[dict[str, Any]],
    strava: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Combine normalized records in provider-priority order."""

    merged: list[dict[str, Any]] = []
    for provider_activities in (garmin, zepp, strava or []):
        batch = _unique_by_id(provider_activities)
        # A fuzzy match must be one-to-one in both directions within a provider.
        # Otherwise the arrival order would decide which real session disappears.
        candidate_map = {}
        for original in batch:
            exact = [i for i, row in enumerate(merged) if _identities(row) & _identities(original)]
            candidate_map[id(original)] = exact or [i for i, row in enumerate(merged)
                if not ({r['source'] for r in _origins(row)} & {r['source'] for r in _origins(original)})
                and _is_duplicate(row, original)]
        counts = {}
        for candidates in candidate_map.values():
            for i in candidates:
                counts[i] = counts.get(i, 0) + 1
        for original in batch:
            item = deepcopy(original)
            item['source_records'] = _origins(item)
            candidates = candidate_map[id(original)]
            if len(candidates) == 1 and counts[candidates[0]] == 1:
                row = merged[candidates[0]]
                row['source_records'] = _origins(row, item)
            else:
                if candidates:
                    item['duplicate_candidates'] = [
                        {'source': merged[i].get('source', 'unknown'), 'id': merged[i]['id']} for i in candidates]
                merged.append(item)
    return sorted(
        merged,
        key=lambda item: (
            str(item.get("started_at") or item.get("date") or ""),
            str(item.get("id") or ""),
        ),
    )


def _origins(*rows):
    records = {}
    for row in rows:
        own = dict(source=row.get('source') or 'unknown',
                   source_activity_id=str(row.get('source_activity_id') or row.get('id') or ''),
                   source_device=row.get('source_device'))
        for record in [own, *(row.get('source_records') or [])]:
            key = (record.get('source'), str(record.get('source_activity_id') or ''))
            records[key] = deepcopy(record)
    return list(records.values())


def _identities(row):
    return {(r['source'], r['source_activity_id']) for r in _origins(row) if r['source_activity_id']}


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
        bool(garmin.get("sport")) and garmin.get("sport") == zepp.get("sport")
        and _start_difference_seconds(garmin, zepp) < 600
        and _overlap_fraction(garmin, zepp) >= 0.70
        and (_duration_matches(garmin, zepp) or _same_garmin_strava_recording(garmin, zepp))
        and _distance_matches_when_available(garmin, zepp)
    )


def _same_garmin_strava_recording(left, right):
    # Garmin's timer and Strava's elapsed time can differ substantially with
    # pauses. Require a tight recording fingerprint before ignoring duration.
    if {left.get('source'), right.get('source')} != {'garmin', 'strava'}:
        return False
    a, b = _positive_number(left.get('km')), _positive_number(right.get('km'))
    hr_a, hr_b = _positive_number(left.get('avg_hr')), _positive_number(right.get('avg_hr'))
    return (
        _start_difference_seconds(left, right) <= 1
        and a is not None and b is not None and abs(a - b) <= 0.01
        and hr_a is not None and hr_b is not None and abs(hr_a - hr_b) <= 1
    )


def _duration_matches(left, right):
    a, b = _positive_number(left.get('duration_s')), _positive_number(right.get('duration_s'))
    return a is not None and b is not None and abs(a - b) / max(a, b) <= 0.20


def _start_difference_seconds(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = _started_at(left)
    right_start = _started_at(right)
    if left_start is None or right_start is None:
        return float("inf")
    return abs(left_start.timestamp() - right_start.timestamp())


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
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None
