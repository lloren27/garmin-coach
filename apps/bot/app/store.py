from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .file_state import atomic_json, serialized_file_state
from .plan_intent import requests_plan_change
from .pending_changes import create_pending_change, allowed_now
from .proposal_repository import FileProposalRepository, PostgresProposalRepository


DATA_DIR = Path("data")
SYNC_FILE = DATA_DIR / "latest_sync.json"
SYNC_HISTORY_FILE = DATA_DIR / "sync_history.jsonl"
CHECKINS_FILE = DATA_DIR / "checkins.jsonl"
PROFILE_FILE = DATA_DIR / "athlete_profile.json"
SYNC_REQUEST_FILE = DATA_DIR / "sync_request.json"
AI_JOBS_FILE = DATA_DIR / "ai_jobs.json"
LAB_TESTS_FILE = DATA_DIR / "lab_tests.json"
WATTWISE_FILE = DATA_DIR / "wattwise_snapshot.json"
TRAINING_PLAN_STATE_FILE = DATA_DIR / "training_plan_state.json"

DATABASE_URL = os.getenv("DATABASE_URL")
STRENGTH_STATE_KEY = "strength_sessions"


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


def save_wattwise(payload: dict[str, Any]) -> dict[str, Any]:
    document = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    if DATABASE_URL:
        save_state_postgres("wattwise_snapshot", document)
        return document

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WATTWISE_FILE.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return document


def load_wattwise() -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_state_postgres("wattwise_snapshot")
    if not WATTWISE_FILE.exists():
        return None
    document = json.loads(WATTWISE_FILE.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else None


def save_strength_state(document: dict[str, Any]) -> dict[str, Any]:
    save_state(STRENGTH_STATE_KEY, document)
    return document


def load_strength_state() -> dict[str, Any] | None:
    return load_state(STRENGTH_STATE_KEY)


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


def save_lab_test(result: dict[str, Any]) -> dict[str, Any]:
    document = {
        "id": str(result.get("id") or uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "source": result.get("source") or {},
        "extracted": result.get("extracted") or {},
        "profile_update": result.get("profile_update") or {},
        "notes": result.get("notes") or [],
        "raw_excerpt": str(result.get("raw_excerpt") or "")[:2500],
    }
    tests = load_lab_tests(100)
    tests.append(document)
    save_lab_tests(tests)
    save_state("pending_lab_test", document)
    return document


def load_lab_tests(limit: int = 10) -> list[dict[str, Any]]:
    if DATABASE_URL:
        state = load_state_postgres("lab_tests") or {}
        tests = state.get("tests") or []
        return tests[-limit:] if isinstance(tests, list) else []

    if not LAB_TESTS_FILE.exists():
        return []
    state = json.loads(LAB_TESTS_FILE.read_text(encoding="utf-8"))
    tests = state.get("tests") if isinstance(state, dict) else state
    return tests[-limit:] if isinstance(tests, list) else []


def load_pending_lab_test() -> dict[str, Any] | None:
    document = load_state("pending_lab_test")
    if document:
        return document
    for item in reversed(load_lab_tests(100)):
        if item.get("status") == "pending":
            return item
    return None


def mark_lab_test_applied(test_id: str | None = None) -> dict[str, Any] | None:
    tests = load_lab_tests(100)
    selected = None
    for item in reversed(tests):
        if test_id and item.get("id") != test_id:
            continue
        if not test_id and item.get("status") != "pending":
            continue
        selected = item
        break
    if not selected:
        return None

    selected["status"] = "applied"
    selected["applied_at"] = datetime.now(timezone.utc).isoformat()
    save_lab_tests(tests)
    pending = load_pending_lab_test()
    if pending and pending.get("id") == selected.get("id"):
        save_state("pending_lab_test", {})
    return selected


def update_lab_test(test_id: str | None, extracted_update: dict[str, Any], profile_update: dict[str, Any]) -> dict[str, Any] | None:
    tests = load_lab_tests(100)
    selected = select_lab_test(tests, test_id)
    if not selected:
        return None

    extracted = dict(selected.get("extracted") or {})
    extracted.update({key: value for key, value in extracted_update.items() if value not in (None, "")})
    update = dict(selected.get("profile_update") or {})
    update.update({key: value for key, value in profile_update.items() if value not in (None, "")})
    selected["extracted"] = extracted
    selected["profile_update"] = update
    selected["status"] = "pending"
    selected["corrected_at"] = datetime.now(timezone.utc).isoformat()

    notes = list(selected.get("notes") or [])
    if "Correccion manual aplicada desde Telegram." not in notes:
        notes.append("Correccion manual aplicada desde Telegram.")
    selected["notes"] = notes

    save_lab_tests(tests)
    save_state("pending_lab_test", selected)
    return selected


def discard_lab_test(test_id: str | None = None) -> dict[str, Any] | None:
    tests = load_lab_tests(100)
    selected = select_lab_test(tests, test_id)
    if not selected:
        return None

    selected["status"] = "discarded"
    selected["discarded_at"] = datetime.now(timezone.utc).isoformat()
    save_lab_tests(tests)
    pending = load_pending_lab_test()
    if pending and pending.get("id") == selected.get("id"):
        save_state("pending_lab_test", {})
    return selected


def select_lab_test(tests: list[dict[str, Any]], test_id: str | None = None) -> dict[str, Any] | None:
    for item in reversed(tests):
        full_id = str(item.get("id") or "")
        if test_id and full_id != test_id and not full_id.startswith(test_id):
            continue
        if not test_id and item.get("status") != "pending":
            continue
        return item
    return None


def save_lab_tests(tests: list[dict[str, Any]]) -> None:
    state = {"tests": tests[-100:]}
    if DATABASE_URL:
        save_state_postgres("lab_tests", state)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAB_TESTS_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


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

@serialized_file_state
def create_ai_job(
    chat_id: str,
    text: str,
    user_id: str | None = None,
    audio_file_id: str | None = None,
    audio_unique_id: str | None = None,
    audio_duration: int | None = None,
    document_file_id: str | None = None,
    document_unique_id: str | None = None,
    document_name: str | None = None,
    document_mime_type: str | None = None,
    document_size: int | None = None,
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
        "document_file_id": document_file_id,
        "document_unique_id": document_unique_id,
        "document_name": document_name,
        "document_mime_type": document_mime_type,
        "document_size": document_size,
        "source_kind": source_kind,
        "response_mode": response_mode,
        "transcript": None,
        "status": "pending",
        "created_at": now,
        "claimed_at": None,
        "completed_at": None,
        "answer": None,
        "error": None,
        "structured_output": None,
        "output_source": None,
    }
    if DATABASE_URL:
        create_ai_job_postgres(document)
        return document

    _bind_job_plan(document, load_active_training_plan(str(chat_id)))
    jobs = load_ai_jobs_file()
    jobs.append(document)
    save_ai_jobs_file(jobs)
    return document


def _bind_job_plan(job, plan):
    requested = requests_plan_change(job['text']) and not job.get('document_file_id')
    job.update({
        'owner_id': job['chat_id'],
        'interaction_mode': 'PLAN_CHANGE' if requested else 'ANALYZE',
        'requested_change_proposal': bool(requested and plan),
        'plan_id': plan['id'] if plan else None,
        'plan_revision': plan.get('revision', 1) if plan else None,
    })


@serialized_file_state
def prepare_proposal_context(job, sources):
    """Return one effective permission; persist generation sources for validation."""
    def prepare(current, repo):
        plan = repo.read_plan(current.get('plan_id'))
        effective = allowed_now(current, plan)
        current['proposal_execution_allowed'] = effective
        current['proposal_evidence_sources'] = sorted(sources)
        return {'training_plan': plan, 'change_proposal_allowed_now': effective}

    if DATABASE_URL:
        import psycopg
        from psycopg.types.json import Jsonb
        with psycopg.connect(DATABASE_URL) as conn:
            row = conn.execute('select document from coach_ai_jobs where id = %s for update', (job['id'],)).fetchone()
            current = row[0]
            context = prepare(current, PostgresProposalRepository(conn))
            conn.execute('update coach_ai_jobs set document = %s where id = %s', (Jsonb(current), job['id']))
            return context
    jobs = load_ai_jobs_file()
    current = next(j for j in jobs if j['id'] == job['id'])
    context = prepare(current, FileProposalRepository(DATA_DIR, TRAINING_PLAN_STATE_FILE))
    save_ai_jobs_file(jobs)
    return context


@serialized_file_state
def complete_ai_job(
    job_id: str,
    status: str = "completed",
    answer: str | None = None,
    error: str | None = None,
    transcript: str | None = None,
    response_mode: str | None = None,
    structured_output: dict[str, Any] | None = None,
    output_source: str | None = None,
) -> dict[str, Any] | None:
    if DATABASE_URL:
        return complete_ai_job_postgres(
            job_id=job_id,
            status=status,
            answer=answer,
            error=error,
            transcript=transcript,
            response_mode=response_mode,
            structured_output=structured_output,
            output_source=output_source,
        )

    jobs = load_ai_jobs_file()
    now = datetime.now(timezone.utc).isoformat()
    completed = None

    for job in jobs:
        if job.get("id") == job_id:
            if output_source == 'ollama':
                proposal = create_pending_change(structured_output, job,
                    FileProposalRepository(DATA_DIR, TRAINING_PLAN_STATE_FILE))
                if proposal:
                    if job.get('status') == 'completed' and job.get('pending_change'):
                        return {**job, '_completion_replayed': True}
                    job['pending_change'] = proposal
            job.update(
                {
                    "status": status,
                    "completed_at": now,
                    "answer": answer,
                    "error": error,
                    "structured_output": structured_output,
                    "output_source": output_source,
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


@serialized_file_state
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


def load_ai_jobs_file() -> list[dict[str, Any]]:
    if not AI_JOBS_FILE.exists():
        return []
    value = json.loads(AI_JOBS_FILE.read_text())
    return value if isinstance(value, list) else []


def save_ai_jobs_file(jobs: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Proposal foreign references and retries must survive job retention.
    atomic_json(AI_JOBS_FILE, jobs)


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


@serialized_file_state
def save_training_plan(
    plan: dict[str, Any],
    owner_id: str,
) -> dict[str, Any]:
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    sessions = []
    for sequence, session in enumerate(plan.get("sessions") or []):
        session_document = dict(session)
        session_document.update(
            {
                "id": str(uuid.uuid4()),
                "training_plan_id": plan_id,
                "owner_id": str(owner_id),
                "sequence": int(session.get("sequence", sequence)),
                "status": str(session.get("status") or "planned"),
                "optional": bool(session.get("optional", False)),
                "created_at": now,
                "updated_at": now,
            }
        )
        sessions.append(session_document)

    plan_document = {
        "id": plan_id,
        "revision": 1,
        "owner_id": str(owner_id),
        "status": "active",
        "start_date": str(plan["start_date"]),
        "end_date": str(plan["end_date"]),
        "objective": plan.get("objective"),
        "mode": plan.get("mode"),
        "source_sync_at": plan.get("source_sync_at"),
        "created_at": now,
        "updated_at": now,
    }

    if DATABASE_URL:
        save_training_plan_postgres(plan_document, sessions)
    else:
        save_training_plan_file(plan_document, sessions)

    return {
        **plan_document,
        "sessions": sessions,
    }


def _training_plan_metadata(
    plan: dict[str, Any],
) -> dict[str, Any]:
    normalized_fields = {
        "id",
        "revision",
        "owner_id",
        "status",
        "start_date",
        "end_date",
        "objective",
        "mode",
        "source_sync_at",
        "created_at",
        "updated_at",
        "sessions",
    }

    return {
        key: value
        for key, value in plan.items()
        if key not in normalized_fields
    }


def _planned_session_metadata(
    session: dict[str, Any],
) -> dict[str, Any]:
    normalized_fields = {
        "id",
        "training_plan_id",
        "owner_id",
        "date",
        "sequence",
        "sport",
        "session_type",
        "status",
        "optional",
        "completed_activity_id",
        "created_at",
        "updated_at",
    }

    return {
        key: value
        for key, value in session.items()
        if key not in normalized_fields
    }


def save_training_plan_postgres(
    plan: dict[str, Any],
    sessions: list[dict[str, Any]],
) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)

        with conn.transaction():
            # Solo puede haber un plan activo por usuario.
            conn.execute(
                """
                update training_plans
                set status = 'superseded',
                    updated_at = now()
                where owner_id = %s
                  and status = 'active'
                """,
                (plan["owner_id"],),
            )

            conn.execute(
                """
                insert into training_plans (
                    id,
                    owner_id,
                    status,
                    start_date,
                    end_date,
                    objective,
                    mode,
                    source_sync_at,
                    document,
                    created_at,
                    updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    plan["id"],
                    plan["owner_id"],
                    plan["status"],
                    plan["start_date"],
                    plan["end_date"],
                    plan.get("objective"),
                    plan.get("mode"),
                    plan.get("source_sync_at"),
                    Jsonb(_training_plan_metadata(plan)),
                    plan["created_at"],
                    plan["updated_at"],
                ),
            )

            for session in sessions:
                conn.execute(
                    """
                    insert into planned_sessions (
                        id,
                        training_plan_id,
                        owner_id,
                        session_date,
                        sequence,
                        sport,
                        session_type,
                        status,
                        optional,
                        completed_activity_id,
                        document,
                        created_at,
                        updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        session["id"],
                        session["training_plan_id"],
                        session["owner_id"],
                        session["date"],
                        session["sequence"],
                        session["sport"],
                        session["session_type"],
                        session["status"],
                        session["optional"],
                        session.get("completed_activity_id"),
                        Jsonb(_planned_session_metadata(session)),
                        session["created_at"],
                        session["updated_at"],
                    ),
                )


def save_training_plan_file(
    plan: dict[str, Any],
    sessions: list[dict[str, Any]],
) -> None:
    state = load_training_plan_state_file()

    plans = state.get("plans") or []
    stored_sessions = state.get("sessions") or []

    for existing in plans:
        if (
            existing.get("owner_id") == plan["owner_id"]
            and existing.get("status") == "active"
        ):
            existing["status"] = "superseded"
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    plans.append(plan)
    stored_sessions.extend(sessions)

    # Keep identities referenced by jobs and proposals.

    retained_plan_ids = {
        str(plan.get("id"))
        for plan in plans
        if plan.get("id")
    }

    stored_sessions = [
        session
        for session in stored_sessions
        if str(session.get("training_plan_id"))
        in retained_plan_ids
    ]

    state = {
        "plans": plans,
        "sessions": stored_sessions,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(TRAINING_PLAN_STATE_FILE, state)


def load_training_plan_state_file() -> dict[str, Any]:
    if not TRAINING_PLAN_STATE_FILE.exists():
        return {
            "plans": [],
            "sessions": [],
        }

    state = json.loads(
        TRAINING_PLAN_STATE_FILE.read_text(encoding="utf-8")
    )

    if not isinstance(state, dict):
        return {
            "plans": [],
            "sessions": [],
        }

    return state


def load_active_training_plan(
    owner_id: str,
) -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_active_training_plan_postgres(owner_id)

    state = load_training_plan_state_file()

    plans = [
        plan
        for plan in state.get("plans") or []
        if plan.get("owner_id") == str(owner_id)
        and plan.get("status") == "active"
    ]

    if not plans:
        return None

    plan = dict(plans[-1])
    plan.setdefault('revision', 1)

    sessions = [
        session
        for session in state.get("sessions") or []
        if session.get("training_plan_id") == plan["id"]
    ]

    sessions.sort(
        key=lambda session: (
            str(session.get("date") or ""),
            int(session.get("sequence", 0)),
        )
    )

    plan["sessions"] = sessions
    return plan


def load_active_training_plan_postgres(
    owner_id: str,
) -> dict[str, Any] | None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)

        row = conn.execute(
            """
            select
                id,
                owner_id,
                status,
                start_date,
                end_date,
                objective,
                mode,
                source_sync_at,
                document,
                created_at,
                updated_at,
                revision
            from training_plans
            where owner_id = %s
              and status = 'active'
            order by created_at desc
            limit 1
            """,
            (str(owner_id),),
        ).fetchone()

        if not row:
            return None

        metadata = row[8] or {}

        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        session_rows = conn.execute(
            """
            select
                id,
                training_plan_id,
                owner_id,
                session_date,
                sequence,
                sport,
                session_type,
                status,
                optional,
                completed_activity_id,
                document,
                created_at,
                updated_at
            from planned_sessions
            where training_plan_id = %s
            order by session_date asc, sequence asc
            """,
            (row[0],),
        ).fetchall()

    result = dict(metadata)

    result.update(
        {
            "id": row[0],
            "revision": row[11],
            "owner_id": row[1],
            "status": row[2],
            "start_date": row[3].isoformat(),
            "end_date": row[4].isoformat(),
            "objective": row[5],
            "mode": row[6],
            "source_sync_at": (
                row[7].isoformat()
                if row[7] is not None
                else None
            ),
            "created_at": row[9].isoformat(),
            "updated_at": row[10].isoformat(),
        }
    )

    sessions: list[dict[str, Any]] = []

    for session_row in session_rows:
        session_metadata = session_row[10] or {}

        if isinstance(session_metadata, str):
            session_metadata = json.loads(session_metadata)

        session = dict(session_metadata)

        session.update(
            {
                "id": session_row[0],
                "training_plan_id": session_row[1],
                "owner_id": session_row[2],
                "date": session_row[3].isoformat(),
                "sequence": session_row[4],
                "sport": session_row[5],
                "session_type": session_row[6],
                "status": session_row[7],
                "optional": session_row[8],
                "completed_activity_id": session_row[9],
                "created_at": session_row[11].isoformat(),
                "updated_at": session_row[12].isoformat(),
            }
        )

        sessions.append(session)

    result["sessions"] = sessions

    return result


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
        row = conn.execute("select id from training_plans where owner_id = %s and status = 'active' for share",
                           (document['chat_id'],)).fetchone()
        plan = PostgresProposalRepository(conn).read_plan(row[0]) if row else None
        _bind_job_plan(document, plan)
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
    structured_output: dict[str, Any] | None = None,
    output_source: str | None = None,
) -> dict[str, Any] | None:
    import psycopg
    from psycopg.types.json import Jsonb

    now = datetime.now(timezone.utc).isoformat()

    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn)

        row = conn.execute(
            "select document from coach_ai_jobs where id = %s for update",
            (job_id,),
        ).fetchone()

        if not row:
            return None

        job = row[0]

        if isinstance(job, str):
            job = json.loads(job)

        if output_source == 'ollama':
            proposal = create_pending_change(structured_output, job, PostgresProposalRepository(conn))
            if proposal:
                if job.get('status') == 'completed' and job.get('pending_change'):
                    return {**job, '_completion_replayed': True}
                job['pending_change'] = proposal

        job.update(
            {
                "status": status,
                "completed_at": now,
                "answer": answer,
                "error": error,
                "structured_output": structured_output,
                "output_source": output_source,
            }
        )

        if transcript is not None:
            job["transcript"] = transcript

        if response_mode is not None:
            job["response_mode"] = response_mode

        conn.execute(
            """
            update coach_ai_jobs
            set status = %s,
                document = %s,
                updated_at = now()
            where id = %s
            """,
            (
                status,
                Jsonb(job),
                job_id,
            ),
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


def save_state(key: str, document: dict[str, Any]) -> None:
    if DATABASE_URL:
        save_state_postgres(key, document)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{key}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_state(key: str) -> dict[str, Any] | None:
    if DATABASE_URL:
        return load_state_postgres(key)
    path = DATA_DIR / f"{key}.json"
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) and document else None


def ensure_schema(conn: Any) -> None:
    # The schema is installed atomically. Once P0.3 exists, avoid DDL altogether:
    # even CREATE INDEX IF NOT EXISTS takes locks that conflict with job updates.
    migrated = conn.execute("""select 1 from pg_attribute
        where attrelid = to_regclass('training_plans') and attname = 'revision'
        and not attisdropped and to_regclass('pending_changes') is not null""").fetchone()
    if migrated:
        return
    conn.execute('select pg_advisory_xact_lock(703003)')
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
    conn.execute(
        """
        create table if not exists training_plans (
            id text primary key,
            owner_id text not null,
            status text not null,
            start_date date not null,
            end_date date not null,
            objective text,
            mode text,
            source_sync_at timestamptz,
            document jsonb not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    conn.execute(
        """
        create table if not exists planned_sessions (
            id text primary key,
            training_plan_id text not null
                references training_plans(id)
                on delete cascade,
            owner_id text not null,
            session_date date not null,
            sequence integer not null default 0,
            sport text not null,
            session_type text not null,
            status text not null default 'planned',
            optional boolean not null default false,
            completed_activity_id text,
            document jsonb not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    conn.execute(
        """
        create index if not exists training_plans_owner_status_idx
        on training_plans (owner_id, status)
        """
    )
    conn.execute(
        """
        create index if not exists planned_sessions_owner_date_idx
        on planned_sessions (owner_id, session_date)
        """
    )
    conn.execute(
        """
        create index if not exists planned_sessions_plan_date_idx
        on planned_sessions (training_plan_id, session_date)
        """
    )
    conn.execute(
        """
        create unique index if not exists training_plans_one_active_per_owner_idx
        on training_plans (owner_id)
        where status = 'active'
        """
    )
    conn.execute(
        """
        create unique index if not exists planned_sessions_plan_date_sequence_idx
        on planned_sessions (training_plan_id, session_date, sequence)
        """
    )
    # Avoid upgrading concurrent read locks to ACCESS EXCLUSIVE on every request.
    # Only an actual migration needs DDL; advisory lock serializes that first run.
    has_revision = conn.execute("""select 1 from pg_attribute
        where attrelid = 'training_plans'::regclass and attname = 'revision' and not attisdropped""").fetchone()
    if not has_revision:
        conn.execute('alter table training_plans add column if not exists revision integer not null default 1 check (revision > 0)')
    conn.execute('''create table if not exists pending_changes (
        id text primary key,
        owner_id text not null,
        training_plan_id text not null references training_plans(id),
        base_plan_revision integer not null check (base_plan_revision > 0),
        source_job_id text not null unique references coach_ai_jobs(id),
        status text not null check (status in ('PENDING','INVALID','APPROVED','REJECTED','APPLIED','EXPIRED','SUPERSEDED')),
        document jsonb not null,
        created_at timestamptz not null default now()
    )''')
