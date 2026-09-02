from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
SYNC_FILE = DATA_DIR / "latest_sync.json"


def save_sync(payload: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    document = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    SYNC_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
    return document


def load_sync() -> dict[str, Any] | None:
    if not SYNC_FILE.exists():
        return None
    return json.loads(SYNC_FILE.read_text())
