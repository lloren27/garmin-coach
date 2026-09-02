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


def number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def pace(distance_km: float, duration_s: float) -> str:
    seconds = int(round(duration_s / distance_km))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}/km"


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


def summarize(activities: list[dict[str, Any]]) -> dict[str, Any]:
    runs = []
    for activity in activities:
        if not is_run(activity):
            continue
        run_date = parse_date(activity.get("startTimeLocal") or activity.get("startTimeGMT"))
        distance_m = number(activity.get("distance"), activity.get("sumDistance"))
        duration_s = number(activity.get("duration"), activity.get("movingDuration"))
        if not run_date or not distance_m or not duration_s or distance_m < 1000:
            continue
        runs.append(
            {
                "date": run_date.isoformat(),
                "name": activity.get("activityName") or "Running",
                "km": round(distance_m / 1000, 2),
                "duration_s": round(duration_s),
                "pace": pace(distance_m / 1000, duration_s),
                "avg_hr": activity.get("averageHR") or activity.get("avgHR"),
            }
        )

    by_week: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        day = date.fromisoformat(run["date"])
        monday = day - timedelta(days=day.weekday())
        by_week[monday.isoformat()].append(run)

    last_28 = TODAY - timedelta(days=27)
    last_56 = TODAY - timedelta(days=55)
    runs_28 = [run for run in runs if date.fromisoformat(run["date"]) >= last_28]
    runs_56 = [run for run in runs if date.fromisoformat(run["date"]) >= last_56]
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
        "plan_level": choose_plan_level(summary),
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
