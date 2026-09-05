from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .sync import API_URL, SYNC_SECRET, main as run_full_sync


STALE_SYNC_MINUTES = int(os.getenv("GARMIN_COACH_STALE_SYNC_MINUTES", "30"))


def headers() -> dict[str, str]:
    return {"X-Sync-Secret": SYNC_SECRET} if SYNC_SECRET else {}


def get_json(path: str) -> dict[str, Any]:
    response = httpx.get(f"{API_URL}{path}", headers=headers(), timeout=20)
    response.raise_for_status()
    return response.json()


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}{path}", json=payload, headers=headers(), timeout=20)
    response.raise_for_status()
    return response.json()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sync_age_minutes(sync_document: dict[str, Any] | None) -> float | None:
    if not sync_document:
        return None
    received_at = parse_datetime(sync_document.get("received_at"))
    if not received_at:
        return None
    return (datetime.now(timezone.utc) - received_at).total_seconds() / 60


def main() -> int:
    request_state = get_json("/sync/request")
    pending_request = request_state.get("request") if request_state.get("pending") else None

    status = get_json("/status")
    age_minutes = sync_age_minutes(status.get("sync"))
    stale = age_minutes is None or age_minutes >= STALE_SYNC_MINUTES

    if not pending_request and not stale:
        print(json.dumps({"ok": True, "action": "skip", "age_minutes": round(age_minutes or 0, 1)}))
        return 0

    reason = "requested" if pending_request else "stale"
    print(json.dumps({"ok": True, "action": "sync", "reason": reason, "age_minutes": age_minutes}))

    try:
        run_full_sync()
    except Exception as exc:
        if pending_request:
            post_json("/sync/request/complete", {"status": "failed", "error": str(exc)[:500]})
        raise

    if pending_request:
        post_json("/sync/request/complete", {"status": "completed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
