from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import httpx
from dotenv import load_dotenv
from garminconnect import Garmin


load_dotenv(Path(__file__).resolve().parents[3] / ".env")

TOKENSTORE = Path(os.getenv("GARMINTOKENS", "~/.garminconnect")).expanduser()
API_URL = os.getenv("GARMIN_COACH_API_URL", "http://127.0.0.1:8000").rstrip("/")
SYNC_SECRET = os.getenv("SYNC_SECRET", "")
TODAY = date.today()
START_DATE = TODAY - timedelta(days=120)
LAST_7 = TODAY - timedelta(days=6)
LAST_28 = TODAY - timedelta(days=27)
LAST_56 = TODAY - timedelta(days=55)
MARATHON_DATE = date(2026, 11, 8)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value[:10]).date()


def activity_type(activity: dict[str, Any]) -> str:
    raw = activity.get("activityType")
    if isinstance(raw, dict):
        return str(raw.get("typeKey") or raw.get("parentTypeKey") or "").lower()
    return str(raw or "").lower()


def is_run(activity: dict[str, Any]) -> bool:
    kind = activity_type(activity)
    name = str(activity.get("activityName") or "").lower()
    return "running" in kind or "run" in name or "correr" in name or "carrera" in name


def sport(activity: dict[str, Any]) -> str:
    kind = activity_type(activity)
    name = str(activity.get("activityName") or "").lower()
    if is_run(activity):
        return "running"
    if any(token in kind for token in ("cycling", "biking", "indoor_cycling")) or any(
        token in name for token in ("cycling", "ciclismo", "bici", "bike")
    ):
        return "cycling"
    if "strength" in kind or "strength" in name or "fuerza" in name:
        return "strength"
    return "other"


def number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def pace(distance_km: float, duration_s: float) -> str:
    seconds = int(round(duration_s / distance_km))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}/km"


def hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def safe_call(label: str, func: Any, *args: Any) -> Any:
    try:
        return func(*args)
    except Exception as exc:
        return {"_unavailable": label, "error": str(exc)}


def get_activities(client: Garmin) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    start = 0
    limit = 100
    while start < 500:
        chunk = client.get_activities(start, limit)
        if not chunk:
            break
        activities.extend(chunk)
        oldest = parse_date(chunk[-1].get("startTimeLocal") or chunk[-1].get("startTimeGMT"))
        if len(chunk) < limit or (oldest and oldest < START_DATE):
            break
        start += limit
    return activities


def normalize_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for activity in activities:
        run_date = parse_date(activity.get("startTimeLocal") or activity.get("startTimeGMT"))
        distance_m = number(activity.get("distance"), activity.get("sumDistance"))
        duration_s = number(activity.get("duration"), activity.get("movingDuration"))
        if not run_date or not duration_s or duration_s < 300:
            continue
        distance_km = round((distance_m or 0) / 1000, 2)
        normalized.append(
            compact_activity(activity, run_date, distance_km, duration_s)
        )
    return sorted(normalized, key=lambda item: item["date"])


def compact_activity(
    activity: dict[str, Any],
    activity_date: date,
    distance_km: float,
    duration_s: float,
) -> dict[str, Any]:
    item = {
        "id": str(activity.get("activityId") or ""),
        "date": activity_date.isoformat(),
        "name": activity.get("activityName") or activity_type(activity) or "Activity",
        "sport": sport(activity),
        "type": activity_type(activity),
        "km": distance_km,
        "duration_s": round(duration_s),
        "hours": hours(duration_s),
        "avg_hr": activity.get("averageHR") or activity.get("avgHR"),
        "max_hr": activity.get("maxHR"),
        "training_effect": activity.get("aerobicTrainingEffect") or activity.get("trainingEffect"),
        "anaerobic_training_effect": activity.get("anaerobicTrainingEffect"),
        "calories": activity.get("calories"),
        "elevation_gain_m": activity.get("elevationGain"),
        "avg_power": activity.get("averagePower") or activity.get("avgPower"),
        "normalized_power": activity.get("normPower") or activity.get("normalizedPower"),
    }
    if distance_km > 0:
        item["pace"] = pace(distance_km, duration_s)
        item["avg_speed_kmh"] = round(distance_km / (duration_s / 3600), 1)
    return item


def summarize(activities: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_activities(activities)
    runs = [activity for activity in normalized if activity["sport"] == "running" and activity["km"] >= 1]

    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        day = date.fromisoformat(run["date"])
        monday = day - timedelta(days=day.weekday())
        by_week[monday.isoformat()].append(run)

    runs_28 = [run for run in runs if date.fromisoformat(run["date"]) >= LAST_28]
    runs_56 = [run for run in runs if date.fromisoformat(run["date"]) >= LAST_56]
    longest = sorted(runs, key=lambda run: run["km"], reverse=True)[:8]

    return {
        "runs_count_120d": len(runs),
        "runs_count_28d": len(runs_28),
        "km_28d": round(sum(run["km"] for run in runs_28), 1),
        "km_56d": round(sum(run["km"] for run in runs_56), 1),
        "avg_weekly_km_8w": round(sum(run["km"] for run in runs_56) / 8, 1),
        "median_run_km_56d": round(median([run["km"] for run in runs_56]), 1) if runs_56 else 0,
        "longest_120d": longest,
        "weekly": [
            {
                "week": week,
                "runs": len(items),
                "km": round(sum(item["km"] for item in items), 1),
                "long_run_km": max(item["km"] for item in items),
            }
            for week, items in sorted(by_week.items())
        ],
        "activities": normalized[-25:],
        "today": summarize_today(normalized),
        "week": summarize_current_week(normalized),
        "sports": {
            "running": summarize_sport(normalized, "running"),
            "cycling": summarize_sport(normalized, "cycling"),
            "strength": summarize_sport(normalized, "strength"),
        },
        "fatigue": summarize_fatigue(normalized),
        "next_workout": recommend_next_workout(normalized),
    }


def summarize_today(activities: list[dict[str, Any]]) -> dict[str, Any]:
    todays = [activity for activity in activities if activity["date"] == TODAY.isoformat()]
    return {
        "date": TODAY.isoformat(),
        "activities": todays,
        "training_minutes": round(sum(activity["duration_s"] for activity in todays) / 60),
        "km": round(sum(activity["km"] for activity in todays), 1),
    }


def summarize_current_week(activities: list[dict[str, Any]]) -> dict[str, Any]:
    monday = TODAY - timedelta(days=TODAY.weekday())
    current = [activity for activity in activities if date.fromisoformat(activity["date"]) >= monday]
    by_sport: dict[str, dict[str, Any]] = {}
    for name in ("running", "cycling", "strength"):
        items = [activity for activity in current if activity["sport"] == name]
        by_sport[name] = {
            "sessions": len(items),
            "km": round(sum(activity["km"] for activity in items), 1),
            "hours": round(sum(activity["duration_s"] for activity in items) / 3600, 1),
        }
    return {
        "start": monday.isoformat(),
        "activities": len(current),
        "km": round(sum(activity["km"] for activity in current), 1),
        "hours": round(sum(activity["duration_s"] for activity in current) / 3600, 1),
        "by_sport": by_sport,
    }


def summarize_sport(activities: list[dict[str, Any]], sport_name: str) -> dict[str, Any]:
    items = [activity for activity in activities if activity["sport"] == sport_name]
    recent_7 = [activity for activity in items if date.fromisoformat(activity["date"]) >= LAST_7]
    recent_28 = [activity for activity in items if date.fromisoformat(activity["date"]) >= LAST_28]
    latest = items[-1] if items else None
    longest = max(items, key=lambda activity: activity["km"], default=None)
    return {
        "sessions_120d": len(items),
        "sessions_7d": len(recent_7),
        "sessions_28d": len(recent_28),
        "km_7d": round(sum(activity["km"] for activity in recent_7), 1),
        "km_28d": round(sum(activity["km"] for activity in recent_28), 1),
        "hours_7d": round(sum(activity["duration_s"] for activity in recent_7) / 3600, 1),
        "hours_28d": round(sum(activity["duration_s"] for activity in recent_28) / 3600, 1),
        "latest": latest,
        "longest": longest,
    }


def summarize_fatigue(activities: list[dict[str, Any]]) -> dict[str, Any]:
    recent_7 = [activity for activity in activities if date.fromisoformat(activity["date"]) >= LAST_7]
    recent_28 = [activity for activity in activities if date.fromisoformat(activity["date"]) >= LAST_28]
    hours_7 = sum(activity["duration_s"] for activity in recent_7) / 3600
    weekly_avg_28 = (sum(activity["duration_s"] for activity in recent_28) / 3600) / 4
    ratio = round(hours_7 / weekly_avg_28, 2) if weekly_avg_28 else 0
    hard_sessions = [
        activity
        for activity in recent_7
        if number(activity.get("training_effect")) and number(activity.get("training_effect")) >= 3.0
    ]
    active_dates = {activity["date"] for activity in recent_7}
    days_since_rest = 0
    day = TODAY
    while day.isoformat() in active_dates:
        days_since_rest += 1
        day -= timedelta(days=1)
    score = 0
    score += 2 if ratio > 1.35 else 1 if ratio > 1.15 else 0
    score += 2 if len(hard_sessions) >= 3 else 1 if len(hard_sessions) == 2 else 0
    score += 1 if days_since_rest >= 4 else 0
    level = "alta" if score >= 4 else "media" if score >= 2 else "baja"
    return {
        "level": level,
        "score": score,
        "hours_7d": round(hours_7, 1),
        "weekly_avg_hours_28d": round(weekly_avg_28, 1),
        "acute_chronic_ratio": ratio,
        "hard_sessions_7d": len(hard_sessions),
        "days_since_rest": days_since_rest,
    }


def recommend_next_workout(activities: list[dict[str, Any]]) -> dict[str, str]:
    fatigue = summarize_fatigue(activities)
    weekday = TODAY.weekday()
    if fatigue["level"] == "alta":
        return {
            "title": "Rodaje regenerativo o descanso",
            "details": "30-45 min muy facil, movilidad y nada de apretar.",
            "reason": "La carga reciente sale alta.",
        }
    if weekday in {0, 4}:
        return {
            "title": "Descanso o fuerza ligera",
            "details": "Core, movilidad y fuerza tecnica 30-40 min.",
            "reason": "Dia util para absorber carga.",
        }
    if weekday == 1:
        return {
            "title": "Calidad corta",
            "details": "10-12 km con 5 x 1 km a 4:45-4:55/km, recuperando 2 min suave.",
            "reason": "Mantiene chispa sin convertir la semana en una carrera.",
        }
    if weekday == 3:
        return {
            "title": "Ritmo maraton",
            "details": "12-14 km con 2-3 bloques a 5:12-5:20/km.",
            "reason": "Especifico para Malaga y sub-3:40.",
        }
    if weekday == 6:
        return {
            "title": "Tirada larga",
            "details": "Progresar la tirada larga sin subir mas de 2-3 km respecto a la anterior.",
            "reason": "La limitacion actual es resistencia especifica.",
        }
    return {
        "title": "Rodaje facil",
        "details": "45-60 min a 5:55-6:30/km. Opcional 6 progresivos.",
        "reason": "Suma base y deja margen para la siguiente sesion clave.",
    }


def compact_wellness(client: Garmin) -> dict[str, Any]:
    daily = safe_call("daily_summary", client.get_user_summary, TODAY.isoformat())
    sleep = safe_call("sleep", client.get_sleep_data, TODAY.isoformat())
    hrv = safe_call("hrv", client.get_hrv_data, TODAY.isoformat())
    readiness = safe_call("training_readiness", client.get_training_readiness, TODAY.isoformat())
    training_status = safe_call("training_status", client.get_training_status, TODAY.isoformat())
    body_battery = safe_call("body_battery", client.get_body_battery, TODAY.isoformat(), TODAY.isoformat())

    return {
        "daily": compact_daily(daily),
        "sleep": compact_sleep(sleep),
        "hrv": compact_hrv(hrv),
        "training_readiness": compact_readiness(readiness),
        "training_status": compact_training_status(training_status),
        "body_battery": compact_body_battery(body_battery),
    }


def compact_daily(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "_unavailable" in value:
        return {}
    return {
        "steps": value.get("totalSteps") or value.get("steps"),
        "resting_hr": value.get("restingHeartRate"),
        "active_kcal": value.get("activeKilocalories"),
        "total_kcal": value.get("totalKilocalories"),
        "intensity_minutes": value.get("intensityMinutes"),
    }


def compact_sleep(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "_unavailable" in value:
        return {}
    dto = value.get("dailySleepDTO") if isinstance(value.get("dailySleepDTO"), dict) else value
    score = value.get("sleepScores") if isinstance(value.get("sleepScores"), dict) else {}
    return {
        "sleep_seconds": dto.get("sleepTimeSeconds") or dto.get("totalSleepSeconds"),
        "deep_seconds": dto.get("deepSleepSeconds"),
        "rem_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "score": score.get("overall", {}).get("value") if isinstance(score.get("overall"), dict) else score.get("overall"),
    }


def compact_hrv(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "_unavailable" in value:
        return {}
    summary = value.get("hrvSummary") if isinstance(value.get("hrvSummary"), dict) else value
    return {
        "last_night_avg": summary.get("lastNightAvg"),
        "weekly_avg": summary.get("weeklyAvg"),
        "status": summary.get("status"),
        "baseline_low": summary.get("baselineLowUpper"),
        "baseline_high": summary.get("baselineBalancedUpper"),
    }


def compact_readiness(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        value = value[0]
    if not isinstance(value, dict) or "_unavailable" in value:
        return {}
    return {
        "score": value.get("score") or value.get("trainingReadinessScore"),
        "level": value.get("level") or value.get("trainingReadinessLevel"),
        "feedback": value.get("feedbackPhrase") or value.get("feedbackShortPhrase"),
    }


def compact_training_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "_unavailable" in value:
        return {}
    return {
        "status": value.get("trainingStatus") or value.get("status"),
        "fitness_trend": value.get("fitnessTrend"),
        "load_message": value.get("loadBalanceMessage"),
    }


def compact_body_battery(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        return {}
    latest = value[-1] if isinstance(value[-1], dict) else {}
    return {
        "charged": latest.get("charged"),
        "drained": latest.get("drained"),
        "start": latest.get("startTimestampLocal"),
        "end": latest.get("endTimestampLocal"),
    }


def choose_plan_level(summary: dict[str, Any]) -> dict[str, str | int]:
    avg8 = summary["avg_weekly_km_8w"]
    longest = summary["longest_120d"][0]["km"] if summary["longest_120d"] else 0
    if avg8 >= 38 and longest >= 20:
        return {"level": "realista", "goal": "bajar de 3:40 si asimilas las semanas clave", "peak_km": 62}
    if avg8 >= 25 and longest >= 16:
        return {"level": "prudente", "goal": "pelear 3:40 con progresion buena", "peak_km": 50}
    return {"level": "base primero", "goal": "sub-3:40 solo si construyes tirada larga sin molestias", "peak_km": 42}


def build_payload() -> dict[str, Any]:
    client = Garmin()
    client.login(str(TOKENSTORE))
    activities = get_activities(client)
    summary = summarize(activities)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "wellness": compact_wellness(client),
        "plan_level": choose_plan_level(summary),
        "race": {
            "name": "Maraton de Malaga",
            "date": MARATHON_DATE.isoformat(),
            "days_until": (MARATHON_DATE - TODAY).days,
            "target": "3:40:00",
            "target_pace": "5:13/km",
        },
    }


def main() -> int:
    payload = build_payload()
    headers = {"X-Sync-Secret": SYNC_SECRET} if SYNC_SECRET else {}
    response = httpx.post(f"{API_URL}/sync", json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
