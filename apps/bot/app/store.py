from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path("data")
SYNC_FILE = DATA_DIR / "latest_sync.json"
SYNC_HISTORY_FILE = DATA_DIR / "sync_history.jsonl"
CHECKINS_FILE = DATA_DIR / "checkins.jsonl"
PROFILE_FILE = DATA_DIR / "athlete_profile.json"
SYNC_REQUEST_FILE = DATA_DIR / "sync_request.json"
AI_JOBS_FILE = DATA_DIR / "ai_jobs.json"
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


def create_ai_job(
    chat_id: str,
    text: str,
    user_id: str | None = None,
    audio_file_id: str | None = None,
    audio_unique_id: str | None = None,
    audio_duration: int | None = None,
    source_kind: str = "text",
    response_mode: str = "text",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    document = {
        "id": str(uuid.uuid4()),
        "chat_id": str(chat_id),
        "user_id": user_id,
        "text": text.strip(),
        "audio_file_id": audio_file_id,
        "audio_unique_id": audio_unique_id,
        "audio_duration": audio_duration,
        "source_kind": source_kind,
        "response_mode": response_mode,
        "transcript": None,
        "status": "pending",
        "created_at": now,
        "claimed_at": None,
        "completed_at": None,
        "answer": None,
        "error": None,
    }
    if DATABASE_URL:
        create_ai_job_postgres(document)
        return document

    jobs = load_ai_jobs_file()
    jobs.append(document)
    save_ai_jobs_file(jobs)
    return document


def claim_next_ai_job() -> dict[str, Any] | None:
    if DATABASE_URL:
        return claim_next_ai_job_postgres()

    jobs = load_ai_jobs_file()
    now = datetime.now(timezone.utc).isoformat()
    claimed = None
    for job in jobs:
        if job.get("status") == "pending" or _stale_running_job(job):
            job["status"] = "running"
            job["claimed_at"] = now
            claimed = job
            break
    if claimed:
        save_ai_jobs_file(jobs)
    return claimed


def complete_ai_job(
    job_id: str,
    status: str = "completed",
    answer: str | None = None,
    error: str | None = None,
    transcript: str | None = None,
    response_mode: str | None = None,
) -> dict[str, Any] | None:
    if DATABASE_URL:
        return complete_ai_job_postgres(job_id, status, answer, error, transcript, response_mode)

    jobs = load_ai_jobs_file()
    now = datetime.now(timezone.utc).isoformat()
    completed = None
    for job in jobs:
        if job.get("id") == job_id:
            job.update(
                {
                    "status": status,
                    "completed_at": now,
                    "answer": answer,
                    "error": error,
                }
            )
            if transcript is not None:
                job["transcript"] = transcript
            if response_mode is not None:
                job["response_mode"] = response_mode
            completed = job
            break
    if completed:
        save_ai_jobs_file(jobs)
    return completed


def load_ai_jobs_file() -> list[dict[str, Any]]:
    if not AI_JOBS_FILE.exists():
        return []
    value = json.loads(AI_JOBS_FILE.read_text())
    return value if isinstance(value, list) else []


def save_ai_jobs_file(jobs: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AI_JOBS_FILE.write_text(json.dumps(jobs[-100:], indent=2, ensure_ascii=True) + "\n")


def _stale_running_job(job: dict[str, Any]) -> bool:
    if job.get("status") != "running":
        return False
    claimed_at = job.get("claimed_at")
    if not claimed_at:
        return True
    try:
        claimed = datetime.fromisoformat(str(claimed_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - claimed.astimezone(timezone.utc)
    return age.total_seconds() > 15 * 60


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


def create_ai_job_postgres(document: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            insert into coach_ai_jobs (id, status, document, created_at)
            values (%s, %s, %s, %s)
            """,
            (document["id"], document["status"], Jsonb(document), document["created_at"]),
        )


def claim_next_ai_job_postgres() -> dict[str, Any] | None:
    import psycopg
    from psycopg.types.json import Jsonb

    now = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        with conn.transaction():
            row = conn.execute(
                """
                select id, document
                from coach_ai_jobs
                where status = 'pending'
                   or (status = 'running' and updated_at < now() - interval '15 minutes')
                order by created_at asc
                limit 1
                for update skip locked
                """
            ).fetchone()
            if not row:
                return None
            job = row[1]
            if isinstance(job, str):
                job = json.loads(job)
            job["status"] = "running"
            job["claimed_at"] = now
            conn.execute(
                """
                update coach_ai_jobs
                set status = %s, document = %s, updated_at = now()
                where id = %s
                """,
                ("running", Jsonb(job), row[0]),
            )
            return job


def complete_ai_job_postgres(
    job_id: str,
    status: str,
    answer: str | None,
    error: str | None,
    transcript: str | None = None,
    response_mode: str | None = None,
) -> dict[str, Any] | None:
    import psycopg
    from psycopg.types.json import Jsonb

    now = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "select document from coach_ai_jobs where id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        job = row[0]
        if isinstance(job, str):
            job = json.loads(job)
        job.update(
            {
                "status": status,
                "completed_at": now,
                "answer": answer,
                "error": error,
            }
        )
        if transcript is not None:
            job["transcript"] = transcript
        if response_mode is not None:
            job["response_mode"] = response_mode
        conn.execute(
            """
            update coach_ai_jobs
            set status = %s, document = %s, updated_at = now()
            where id = %s
            """,
            (status, Jsonb(job), job_id),
        )
        return job


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
    conn.execute(
        """
        create table if not exists coach_ai_jobs (
            id text primary key,
            status text not null,
            document jsonb not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    conn.execute(
        """
        create index if not exists coach_ai_jobs_status_created_idx
        on coach_ai_jobs (status, created_at)
        """
    )
