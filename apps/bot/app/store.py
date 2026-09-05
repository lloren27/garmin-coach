from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
SYNC_FILE = DATA_DIR / "latest_sync.json"
SYNC_HISTORY_FILE = DATA_DIR / "sync_history.jsonl"
CHECKINS_FILE = DATA_DIR / "checkins.jsonl"
PROFILE_FILE = DATA_DIR / "athlete_profile.json"
SYNC_REQUEST_FILE = DATA_DIR / "sync_request.json"
DATABASE_URL = os.getenv("DATABASE_URL")


def save_sync(payload: dict[str, Any]) -> dict[str, Any]:
    document = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    if DATABASE_URL:
        save_sync_postgres(document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
    with SYNC_HISTORY_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=True) + "\n")
    return document


def load_sync() -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_sync_postgres()

    if not SYNC_FILE.exists():
        return None
    return json.loads(SYNC_FILE.read_text())


def load_sync_history(limit: int = 10) -> list[dict[str, Any]]:
    if DATABASE_URL:
        return load_sync_history_postgres(limit)

    if not SYNC_HISTORY_FILE.exists():
        return []
    rows = []
    for line in SYNC_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def save_checkin(checkin: dict[str, Any]) -> dict[str, Any]:
    document = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkin": checkin,
    }
    if DATABASE_URL:
        save_checkin_postgres(document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CHECKINS_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, ensure_ascii=True) + "\n")
    return document


def load_checkins(limit: int = 5) -> list[dict[str, Any]]:
    if DATABASE_URL:
        return load_checkins_postgres(limit)

    if not CHECKINS_FILE.exists():
        return []
    rows = []
    for line in CHECKINS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    document = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
    }
    if DATABASE_URL:
        save_profile_postgres(document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
    return document


def load_profile() -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_profile_postgres()

    if not PROFILE_FILE.exists():
        return None
    return json.loads(PROFILE_FILE.read_text())


def save_sync_request(requested_by: str | None = None) -> dict[str, Any]:
    document = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": requested_by,
        "status": "pending",
        "completed_at": None,
        "last_error": None,
    }
    if DATABASE_URL:
        save_state_postgres("sync_request", document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_REQUEST_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
    return document


def load_sync_request() -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_state_postgres("sync_request")

    if not SYNC_REQUEST_FILE.exists():
        return None
    return json.loads(SYNC_REQUEST_FILE.read_text())


def complete_sync_request(status: str = "completed", error: str | None = None) -> dict[str, Any] | None:
    document = load_sync_request()
    if not document:
        return None
    document.update(
        {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": error,
        }
    )
    if DATABASE_URL:
        save_state_postgres("sync_request", document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_REQUEST_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
    return document


def save_sync_postgres(document: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            insert into sync_state (key, document, updated_at)
            values (%s, %s, now())
            on conflict (key)
            do update set document = excluded.document, updated_at = excluded.updated_at
            """,
            ("latest", Jsonb(document)),
        )
        conn.execute(
            "insert into sync_history (document, received_at) values (%s, %s)",
            (Jsonb(document), document["received_at"]),
        )


def load_sync_postgres() -> dict[str, Any] | None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "select document from sync_state where key = %s",
            ("latest",),
        ).fetchone()

    if not row:
        return None
    document = row[0]
    if isinstance(document, str):
        return json.loads(document)
    return document


def load_sync_history_postgres(limit: int) -> list[dict[str, Any]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            select document
            from sync_history
            order by received_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()

    history = []
    for row in rows:
        document = row[0]
        if isinstance(document, str):
            document = json.loads(document)
        history.append(document)
    return list(reversed(history))


def save_checkin_postgres(document: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        conn.execute(
            "insert into coach_checkins (document, created_at) values (%s, %s)",
            (Jsonb(document), document["created_at"]),
        )


def load_checkins_postgres(limit: int) -> list[dict[str, Any]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            select document
            from coach_checkins
            order by created_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()

    checkins = []
    for row in rows:
        document = row[0]
        if isinstance(document, str):
            document = json.loads(document)
        checkins.append(document)
    return list(reversed(checkins))


def save_profile_postgres(document: dict[str, Any]) -> None:
    save_state_postgres("athlete_profile", document)


def load_profile_postgres() -> dict[str, Any] | None:
    return load_state_postgres("athlete_profile")


def save_state_postgres(key: str, document: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            insert into sync_state (key, document, updated_at)
            values (%s, %s, now())
            on conflict (key)
            do update set document = excluded.document, updated_at = excluded.updated_at
            """,
            (key, Jsonb(document)),
        )


def load_state_postgres(key: str) -> dict[str, Any] | None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "select document from sync_state where key = %s",
            (key,),
        ).fetchone()

    if not row:
        return None
    document = row[0]
    if isinstance(document, str):
        return json.loads(document)
    return document


def ensure_schema(conn: Any) -> None:
    conn.execute(
        """
        create table if not exists sync_state (
            key text primary key,
            document jsonb not null,
            updated_at timestamptz not null default now()
        )
        """
    )
    conn.execute(
        """
        create table if not exists sync_history (
            id bigserial primary key,
            document jsonb not null,
            received_at timestamptz not null default now()
        )
        """
    )
    conn.execute(
        """
        create table if not exists coach_checkins (
            id bigserial primary key,
            document jsonb not null,
            created_at timestamptz not null default now()
        )
        """
    )
