from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[3] / ".env")
MADRID_TZ = ZoneInfo("Europe/Madrid")
WATTWISE_API_URL = os.getenv("WATTWISE_API_URL", "http://127.0.0.1:8010").rstrip("/")
WATTWISE_ACCESS_TOKEN = os.getenv("WATTWISE_ACCESS_TOKEN", "")
WATTWISE_OWNER_SECRET = os.getenv("WATTWISE_OWNER_SECRET", "")
WATTWISE_AI_CONTEXT = os.getenv("WATTWISE_AI_CONTEXT", "1")
WATTWISE_AI_LOOKBACK_DAYS = int(os.getenv("WATTWISE_AI_LOOKBACK_DAYS", "28"))
_runtime_access_token = WATTWISE_ACCESS_TOKEN


def fetch_wattwise_context() -> dict[str, Any] | None:
    if WATTWISE_AI_CONTEXT.strip().lower() in {"0", "false", "no", "off"}:
        return None
    if not WATTWISE_ACCESS_TOKEN:
        return None

    end = datetime.now(MADRID_TZ).date()
    start = end - timedelta(days=max(WATTWISE_AI_LOOKBACK_DAYS - 1, 0))
    query = f"from={start.isoformat()}&to={end.isoformat()}"
    try:
        with httpx.Client(timeout=20, headers=auth_headers()) as client:
            activities = _get_json(client, "/v1/activities", params={"limit": 20}).get("data", [])
            coggan = _get_json(client, f"/v1/performance/coggan?{query}")
            load = _get_json(client, f"/v1/performance/load-fitness?{query}")
            athlete = _get_json(client, "/v1/athlete")
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)[:180]}

    cycling_metrics = []
    for item in coggan.get("items", []):
        values = item.get("values") or {}
        if values.get("tss") is None and values.get("intensity_factor") is None:
            continue
        cycling_metrics.append(
            {
                "date": item.get("local_date"),
                "activity_id": item.get("activity_id"),
                "tss": _round(values.get("tss")),
                "intensity_factor": _round(values.get("intensity_factor"), 2),
                "variability_index": _round(values.get("variability_index"), 2),
            }
        )

    load_items = load.get("items") or []
    latest_load = next((item for item in reversed(load_items) if (item.get("values") or {}).get("load") is not None), None)
    signature = athlete.get("fitness_signature") or {}
    return {
        "status": "ok",
        "source": "local_wattwise_core",
        "generated_at": datetime.now(MADRID_TZ).isoformat(timespec="seconds"),
        "lookback_days": WATTWISE_AI_LOOKBACK_DAYS,
        "note": "Use Wattwise mainly for cycling power/load. Running imports may be sparse; use Garmin Coach summary for running pace, distance and HR.",
        "recent_activities": [_compact_activity(item) for item in activities[:12]],
        "cycling_power_metrics": cycling_metrics[-12:],
        "latest_load": latest_load.get("values") if latest_load else None,
        "fitness_signature": {
            "sport": signature.get("signature_type") or athlete.get("current_sport"),
            "effective_date": signature.get("effective_date"),
            "ftp_w": _round(signature.get("ftp_w"), 0),
        },
    }


def auth_headers() -> dict[str, str]:
    token = access_token()
    if not token:
        raise RuntimeError("Falta WATTWISE_OWNER_SECRET o WATTWISE_ACCESS_TOKEN")
    return {"Authorization": f"Bearer {token}"}


def access_token() -> str:
    global _runtime_access_token
    if _runtime_access_token and not _token_expired(_runtime_access_token):
        return _runtime_access_token
    if not WATTWISE_OWNER_SECRET:
        return _runtime_access_token
    response = httpx.post(
        f"{WATTWISE_API_URL}/v1/auth/token",
        json={"owner_secret": WATTWISE_OWNER_SECRET},
        timeout=20,
    )
    response.raise_for_status()
    _runtime_access_token = str(response.json().get("access_token") or "")
    return _runtime_access_token


def _token_expired(token: str) -> bool:
    try:
        encoded = token.split(".")[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return float(payload.get("exp") or 0) <= time.time() + 60
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return True


def _get_json(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(f"{WATTWISE_API_URL}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _compact_activity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": item.get("local_date"),
        "sport": item.get("sport"),
        "distance_km": _round((item.get("distance_m") or 0) / 1000, 1) if item.get("distance_m") else None,
        "moving_min": _round((item.get("moving_time_s") or 0) / 60, 1) if item.get("moving_time_s") else None,
        "avg_power_w": item.get("avg_power_w"),
        "has_power": item.get("has_power"),
        "has_hr": item.get("has_hr"),
        "has_gps": item.get("has_gps"),
    }


def _round(value: Any, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
