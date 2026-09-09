from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import fmean, pstdev
from typing import Any


def enrich_running_load(
    activities: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    reference_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    athlete = _profile_payload(profile)
    max_hr = _number(athlete.get("max_hr"))
    resting_hr = _number(athlete.get("resting_hr"))
    sex = _normalize_sex(athlete.get("sex"))
    can_estimate = bool(max_hr and resting_hr and max_hr > resting_hr + 20 and sex)
    model = "trimp_estimado" if can_estimate else "garmin"

    enriched = []
    metrics = []
    for activity in activities:
        item = dict(activity)
        if item.get("sport") == "running":
            direct_load = _number(item.get("training_load"))
            if model == "trimp_estimado":
                load, hr_reserve_pct = _banister_trimp(item, max_hr or 0, resting_hr or 0, sex)
                source = "trimp_estimado" if load is not None else None
            elif direct_load and direct_load > 0:
                load = direct_load
                source = "garmin"
                hr_reserve_pct = None
            else:
                load = None
                source = None
                hr_reserve_pct = None

            if load is not None:
                item["running_load"] = round(load, 1)
                item["running_load_source"] = source
                item["hr_reserve_pct"] = hr_reserve_pct
                metrics.append(
                    {
                        "activity_id": item.get("id"),
                        "date": item.get("date"),
                        "name": item.get("name"),
                        "load": round(load, 1),
                        "source": source,
                        "hr_reserve_pct": hr_reserve_pct,
                        "duration_min": round((_number(item.get("duration_s")) or 0) / 60, 1),
                    }
                )
        enriched.append(item)

    return enriched, _summarize(metrics, reference_date, max_hr, resting_hr, sex, model)


def _banister_trimp(
    activity: dict[str, Any],
    max_hr: float,
    resting_hr: float,
    sex: str,
) -> tuple[float | None, float | None]:
    duration_s = _number(activity.get("duration_s"))
    avg_hr = _number(activity.get("avg_hr"))
    if not duration_s or duration_s <= 0 or not avg_hr:
        return None, None
    reserve = _hr_reserve_fraction(avg_hr, max_hr, resting_hr)
    if reserve is None:
        return None, None
    factor_a, factor_b = (0.86, 1.67) if sex == "mujer" else (0.64, 1.92)
    duration_min = duration_s / 60
    load = duration_min * reserve * factor_a * math.exp(factor_b * reserve)
    return round(load, 1), round(reserve * 100)


def _summarize(
    metrics: list[dict[str, Any]],
    reference_date: date,
    max_hr: float | None,
    resting_hr: float | None,
    sex: str,
    model: str,
) -> dict[str, Any]:
    daily = defaultdict(float)
    for item in metrics:
        activity_date = _parse_date(item.get("date"))
        if activity_date:
            daily[activity_date] += _number(item.get("load")) or 0

    days_7 = [reference_date - timedelta(days=offset) for offset in range(6, -1, -1)]
    days_28 = [reference_date - timedelta(days=offset) for offset in range(27, -1, -1)]
    values_7 = [daily[day] for day in days_7]
    values_28 = [daily[day] for day in days_28]
    acute = round(sum(values_7), 1)
    chronic_weekly = round(sum(values_28) / 4, 1)
    acwr = round(acute / chronic_weekly, 2) if chronic_weekly > 0 else None
    mean_7 = fmean(values_7) if values_7 else 0
    deviation_7 = pstdev(values_7) if len(values_7) > 1 else 0
    monotony = round(mean_7 / deviation_7, 2) if deviation_7 > 0 else None
    strain = round(acute * monotony, 1) if monotony is not None else None
    recent = [item for item in metrics if (_parse_date(item.get("date")) or date.min) >= days_28[0]]
    direct_count = sum(1 for item in recent if item.get("source") == "garmin")
    estimated_count = sum(1 for item in recent if item.get("source") == "trimp_estimado")

    weekly = defaultdict(lambda: {"load": 0.0, "sessions": 0, "km": 0.0})
    for item in metrics:
        activity_date = _parse_date(item.get("date"))
        if not activity_date:
            continue
        monday = activity_date - timedelta(days=activity_date.weekday())
        weekly[monday]["load"] += _number(item.get("load")) or 0
        weekly[monday]["sessions"] += 1

    return {
        "available": bool(metrics),
        "model": model,
        "unit": "TRIMP" if model == "trimp_estimado" else "carga Garmin",
        "reference_date": reference_date.isoformat(),
        "acute_load_7d": acute,
        "chronic_weekly_load_28d": chronic_weekly,
        "acwr": acwr,
        "acwr_status": _acwr_status(acwr),
        "monotony_7d": monotony,
        "strain_7d": strain,
        "running_days_7d": sum(1 for value in values_7 if value > 0),
        "source_counts_28d": {"garmin": direct_count, "estimated_trimp": estimated_count},
        "profile_basis": {
            "max_hr": round(max_hr) if max_hr else None,
            "resting_hr": round(resting_hr) if resting_hr else None,
            "sex": sex or None,
        },
        "latest": metrics[-1] if metrics else None,
        "weekly": [
            {
                "week": week.isoformat(),
                "sessions": values["sessions"],
                "load": round(values["load"], 1),
            }
            for week, values in sorted(weekly.items())
        ][-12:],
        "method": (
            "Banister TRIMP estimated from average heart rate."
            if model == "trimp_estimado"
            else "Garmin activityTrainingLoad."
        ),
        "caveat": "ACWR describes a recent load change; it does not predict injury by itself.",
    }


def _acwr_status(value: float | None) -> str:
    if value is None:
        return "sin_base"
    if value < 0.8:
        return "baja"
    if value <= 1.3:
        return "estable"
    if value <= 1.5:
        return "elevada"
    return "pico_alto"


def _hr_reserve_pct(value: Any, max_hr: float | None, resting_hr: float | None) -> float | None:
    avg_hr = _number(value)
    if not avg_hr or not max_hr or not resting_hr:
        return None
    reserve = _hr_reserve_fraction(avg_hr, max_hr, resting_hr)
    return round(reserve * 100) if reserve is not None else None


def _hr_reserve_fraction(avg_hr: float, max_hr: float, resting_hr: float) -> float | None:
    denominator = max_hr - resting_hr
    if denominator <= 0:
        return None
    return min(max((avg_hr - resting_hr) / denominator, 0.0), 1.0)


def _profile_payload(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    value = profile.get("profile", profile)
    return value if isinstance(value, dict) else {}


def _normalize_sex(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"mujer", "female", "f", "woman"}:
        return "mujer"
    if text in {"hombre", "male", "m", "man"}:
        return "hombre"
    return ""


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
